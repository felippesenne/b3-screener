from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from indicators import ema, rsi_wilder, sma


_EVENT_COLUMNS = [
    "EntryPrice",
    "ExitPrice",
    "PartialExitPrice",
    "StopHitPrice",
    "InitialStopPoint",
    "ActiveStop",
    "EntryTrigger",
    "ExitTrigger",
    "SetupTrigger",
]

_PRICE_OVERLAYS = ["MME9", "MME20", "MME21", "MME30", "MME50", "MMS10"]
_RSI_COLUMNS = ["IFR2", "IFR14"]


def _finite(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except Exception:
        return False


def _first_finite(row: pd.Series, names: list[str]):
    for name in names:
        if name in row.index and _finite(row.get(name)):
            return float(row.get(name))
    return None


def _infer_setup_id(
    setup_id: str | None,
    trades: pd.DataFrame | None,
    orders: pd.DataFrame | None,
) -> str | None:
    if setup_id:
        return setup_id
    for source in (trades, orders):
        if source is None or source.empty or "Setup" not in source.columns:
            continue
        values = source["Setup"].dropna().astype(str)
        if not values.empty:
            return values.iloc[0]
    return None


def _add_strategy_indicators(
    frame: pd.DataFrame,
    setup_id: str | None,
    exit_label: str | None,
) -> None:
    close = frame["Close"].astype(float)

    overlay_names: set[str] = set()
    rsi_names: set[str] = set()

    if setup_id in {"setup_91_buy", "setup_91_sell"}:
        overlay_names.add("MME9")
    if setup_id in {"landry_adjusted_buy", "bowtie_buy", "bowtie_sell"}:
        overlay_names.update({"MMS10", "MME20", "MME30"})
    if setup_id in {"landry_classic_buy", "landry_classic_sell"}:
        overlay_names.update({"MME20", "MME50"})
    if setup_id == "ifr2_ifr14_rolling_buy":
        rsi_names.update({"IFR2", "IFR14"})

    if exit_label:
        if "MME9" in exit_label:
            overlay_names.add("MME9")
        if "MME21" in exit_label:
            overlay_names.add("MME21")
        if "IFR(2)" in exit_label:
            rsi_names.add("IFR2")

    series = {
        "MME9": lambda: ema(close, 9),
        "MME20": lambda: ema(close, 20),
        "MME21": lambda: ema(close, 21),
        "MME30": lambda: ema(close, 30),
        "MME50": lambda: ema(close, 50),
        "MMS10": lambda: sma(close, 10),
        "IFR2": lambda: rsi_wilder(close, 2),
        "IFR14": lambda: rsi_wilder(close, 14),
    }
    for name in sorted(overlay_names | rsi_names):
        frame[name] = series[name]()


def _apply_orders(frame: pd.DataFrame, orders: pd.DataFrame | None) -> None:
    if orders is None or orders.empty or "ActiveDate" not in orders.columns or "TriggerPrice" not in orders.columns:
        return

    normalized = orders.copy()
    normalized["ActiveDate"] = pd.to_datetime(normalized["ActiveDate"], errors="coerce")
    for _, order in normalized.iterrows():
        active_date = order.get("ActiveDate")
        trigger = order.get("TriggerPrice")
        if pd.isna(active_date) or active_date not in frame.index or not _finite(trigger):
            continue
        phase = str(order.get("Phase", "")).lower()
        if phase == "entry":
            frame.loc[active_date, "EntryTrigger"] = float(trigger)
        elif phase == "exit":
            frame.loc[active_date, "ExitTrigger"] = float(trigger)
        else:
            frame.loc[active_date, "SetupTrigger"] = float(trigger)


def build_operational_chart_frame(
    df: pd.DataFrame,
    trades: pd.DataFrame | None,
    equity_curve: pd.DataFrame | None = None,
    orders: pd.DataFrame | None = None,
    *,
    setup_id: str | None = None,
    exit_label: str | None = None,
) -> pd.DataFrame:
    """Combine OHLC, trade events, triggers, stops and strategy indicators.

    The output is intentionally chart-library agnostic. Entry/exit triggers are
    sourced from the actual order rows produced by the backtest engine; dynamic
    stops are taken from the equity curve when the engine exposes them.
    """
    required = ["Open", "High", "Low", "Close"]
    missing = [name for name in required if name not in df.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")

    frame = df[required].copy().sort_index()
    frame.index = pd.to_datetime(frame.index)
    frame.index.name = "Date"
    for column in _EVENT_COLUMNS:
        frame[column] = float("nan")

    inferred_setup = _infer_setup_id(setup_id, trades, orders)
    _add_strategy_indicators(frame, inferred_setup, exit_label)
    _apply_orders(frame, orders)

    if equity_curve is not None and not equity_curve.empty:
        eq = equity_curve.copy()
        eq.index = pd.to_datetime(eq.index)
        stop_column = next(
            (name for name in ("TrailingStop", "CurrentStop", "ActiveStop") if name in eq.columns),
            None,
        )
        if stop_column is not None:
            frame["ActiveStop"] = pd.to_numeric(eq[stop_column], errors="coerce").reindex(frame.index)

    if trades is None or trades.empty:
        return frame.reset_index()

    dynamic_stop_available = frame["ActiveStop"].notna().any()

    for _, trade in trades.iterrows():
        entry_date = pd.to_datetime(trade.get("EntryDate"), errors="coerce")
        exit_date = pd.to_datetime(trade.get("ExitDate"), errors="coerce")
        partial_date = pd.to_datetime(trade.get("PartialExitDate"), errors="coerce")

        entry_price = _first_finite(trade, ["EntryPrice"])
        exit_price = _first_finite(trade, ["ExitPrice", "FinalExitPrice"])
        partial_price = _first_finite(trade, ["PartialExitPrice"])
        initial_stop = _first_finite(trade, ["InitialStop", "InitialStopPrice", "StopPrice"])

        if not pd.isna(entry_date) and entry_date in frame.index:
            if entry_price is not None:
                frame.loc[entry_date, "EntryPrice"] = entry_price
            if initial_stop is not None:
                frame.loc[entry_date, "InitialStopPoint"] = initial_stop

        if not pd.isna(partial_date) and partial_date in frame.index and partial_price is not None:
            frame.loc[partial_date, "PartialExitPrice"] = partial_price

        if not pd.isna(exit_date) and exit_date in frame.index and exit_price is not None:
            frame.loc[exit_date, "ExitPrice"] = exit_price
            reason = str(trade.get("ExitReason", "")).lower()
            if "stop" in reason or "breakeven" in reason or "ifr14_exit" in reason:
                frame.loc[exit_date, "StopHitPrice"] = exit_price

        if (
            not dynamic_stop_available
            and initial_stop is not None
            and not pd.isna(entry_date)
            and not pd.isna(exit_date)
        ):
            mask = (frame.index >= entry_date) & (frame.index <= exit_date)
            frame.loc[mask, "ActiveStop"] = initial_stop

    return frame.reset_index()


def slice_trade_window(
    chart_frame: pd.DataFrame,
    trade: pd.Series,
    *,
    padding_bars: int = 12,
) -> pd.DataFrame:
    """Return a local chart window around one completed trade."""
    if chart_frame.empty or "Date" not in chart_frame.columns:
        return chart_frame.copy()
    if padding_bars < 0:
        raise ValueError("padding_bars não pode ser negativo.")

    dates = pd.to_datetime(chart_frame["Date"])
    entry = pd.to_datetime(trade.get("EntryDate"), errors="coerce")
    exit_ = pd.to_datetime(trade.get("ExitDate"), errors="coerce")
    if pd.isna(entry) or pd.isna(exit_):
        return chart_frame.copy()

    entry_positions = dates[dates >= entry].index
    exit_positions = dates[dates <= exit_].index
    if len(entry_positions) == 0 or len(exit_positions) == 0:
        return chart_frame.copy()

    start = max(0, int(entry_positions[0]) - padding_bars)
    end = min(len(chart_frame) - 1, int(exit_positions[-1]) + padding_bars)
    return chart_frame.iloc[start : end + 1].copy()


def _indicator_thresholds(setup_id: str | None, exit_label: str | None) -> list[float]:
    values: list[float] = []
    if setup_id == "ifr2_ifr14_rolling_buy":
        values.extend([10.0, 70.0])
    if exit_label == "IFR(2) retorna para 70/30":
        values.extend([30.0, 70.0])
    elif exit_label == "IFR(2) retorna para 90/10":
        values.extend([10.0, 90.0])
    return sorted(set(values))


def build_operational_figure(
    chart_frame: pd.DataFrame,
    *,
    setup_id: str | None = None,
    exit_label: str | None = None,
    selected_trade: pd.Series | None = None,
):
    """Build a TradingView/Profit-style interactive operational chart."""
    if chart_frame.empty:
        return go.Figure()

    frame = chart_frame.copy()
    frame["Date"] = pd.to_datetime(frame["Date"])
    has_rsi = any(name in frame.columns and frame[name].notna().any() for name in _RSI_COLUMNS)
    rows = 2 if has_rsi else 1
    row_heights = [0.74, 0.26] if has_rsi else [1.0]
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025 if has_rsi else 0.0,
        row_heights=row_heights,
    )

    fig.add_trace(
        go.Candlestick(
            x=frame["Date"],
            open=frame["Open"],
            high=frame["High"],
            low=frame["Low"],
            close=frame["Close"],
            name="Preço",
            increasing_line_color="#16a34a",
            decreasing_line_color="#dc2626",
            increasing_fillcolor="#16a34a",
            decreasing_fillcolor="#dc2626",
            whiskerwidth=0.35,
        ),
        row=1,
        col=1,
    )

    overlay_styles = {
        "MME9": ("#2563eb", 1.7),
        "MMS10": ("#7c3aed", 1.5),
        "MME20": ("#ea580c", 1.5),
        "MME21": ("#d97706", 1.5),
        "MME30": ("#0f766e", 1.5),
        "MME50": ("#111827", 1.7),
    }
    for name in _PRICE_OVERLAYS:
        if name not in frame.columns or not frame[name].notna().any():
            continue
        color, width = overlay_styles[name]
        fig.add_trace(
            go.Scatter(
                x=frame["Date"],
                y=frame[name],
                mode="lines",
                name=name,
                line={"color": color, "width": width},
                hovertemplate=f"{name}: %{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    line_specs = [
        ("SetupTrigger", "Gatilho do setup", "#475569", "dot"),
        ("EntryTrigger", "Gatilho de entrada", "#2563eb", "dot"),
        ("ExitTrigger", "Gatilho de saída", "#be123c", "dot"),
        ("ActiveStop", "Stop vigente", "#f59e0b", "dash"),
    ]
    for field, label, color, dash in line_specs:
        if field not in frame.columns or not frame[field].notna().any():
            continue
        fig.add_trace(
            go.Scatter(
                x=frame["Date"],
                y=frame[field],
                mode="lines",
                name=label,
                connectgaps=False,
                line={"color": color, "width": 2, "dash": dash, "shape": "hv"},
                hovertemplate=f"{label}: %{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    marker_specs = [
        ("EntryPrice", "Entrada", "triangle-up", "#00a152", 16),
        ("PartialExitPrice", "Saída parcial", "diamond", "#7c3aed", 13),
        ("ExitPrice", "Saída", "triangle-down", "#2563eb", 16),
        ("InitialStopPoint", "Stop inicial", "square", "#f59e0b", 10),
        ("StopHitPrice", "Stop acionado", "x", "#b91c1c", 14),
    ]
    for field, label, symbol, color, size in marker_specs:
        if field not in frame.columns:
            continue
        points = frame[frame[field].notna()]
        if points.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=points["Date"],
                y=points[field],
                mode="markers",
                name=label,
                marker={"symbol": symbol, "color": color, "size": size, "line": {"width": 1, "color": "white"}},
                hovertemplate=f"{label}<br>%{{x|%d/%m/%Y}}<br>R$ %{{y:.2f}}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if selected_trade is not None:
        entry_date = pd.to_datetime(selected_trade.get("EntryDate"), errors="coerce")
        exit_date = pd.to_datetime(selected_trade.get("ExitDate"), errors="coerce")
        if not pd.isna(entry_date) and not pd.isna(exit_date):
            fig.add_vrect(
                x0=entry_date,
                x1=exit_date,
                fillcolor="rgba(37,99,235,0.07)",
                line_width=0,
                layer="below",
                row=1,
                col=1,
            )
        entry_signal = pd.to_datetime(selected_trade.get("EntrySignalDate"), errors="coerce")
        exit_signal = pd.to_datetime(selected_trade.get("ExitSignalDate"), errors="coerce")
        if not pd.isna(entry_signal):
            fig.add_vline(
                x=entry_signal,
                line_width=1,
                line_dash="dot",
                line_color="#2563eb",
                annotation_text="Sinal entrada",
                annotation_position="top left",
                row=1,
                col=1,
            )
        if not pd.isna(exit_signal):
            fig.add_vline(
                x=exit_signal,
                line_width=1,
                line_dash="dot",
                line_color="#be123c",
                annotation_text="Sinal saída",
                annotation_position="top right",
                row=1,
                col=1,
            )

    if has_rsi:
        rsi_styles = {"IFR2": "#7c3aed", "IFR14": "#2563eb"}
        for name in _RSI_COLUMNS:
            if name not in frame.columns or not frame[name].notna().any():
                continue
            fig.add_trace(
                go.Scatter(
                    x=frame["Date"],
                    y=frame[name],
                    mode="lines",
                    name=name,
                    line={"color": rsi_styles[name], "width": 1.8},
                    hovertemplate=f"{name}: %{{y:.1f}}<extra></extra>",
                ),
                row=2,
                col=1,
            )
        for level in _indicator_thresholds(setup_id, exit_label):
            fig.add_hline(
                y=level,
                line_width=1,
                line_dash="dash",
                line_color="#94a3b8",
                annotation_text=str(int(level)),
                annotation_position="right",
                row=2,
                col=1,
            )
        fig.update_yaxes(title_text="IFR", range=[0, 100], fixedrange=False, row=2, col=1)

    height = 800 if has_rsi else 650
    fig.update_layout(
        height=height,
        template="plotly_white",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
        hovermode="x",
        spikedistance=-1,
        hoverdistance=80,
        dragmode="zoom",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0},
        xaxis_rangeslider_visible=False,
        modebar_add=["drawline", "drawrect", "eraseshape"],
    )
    fig.update_yaxes(title_text="Preço (R$)", fixedrange=False, row=1, col=1)
    fig.update_xaxes(
        showspikes=True,
        spikecolor="#64748b",
        spikethickness=1,
        spikedash="dot",
        spikesnap="cursor",
        showline=True,
        linecolor="#cbd5e1",
        gridcolor="#e2e8f0",
    )
    return fig


def operational_chart_spec() -> dict:
    """Compatibility shim kept for older callers while the UI migrates to Plotly."""
    return {"deprecated": True, "replacement": "build_operational_figure"}
