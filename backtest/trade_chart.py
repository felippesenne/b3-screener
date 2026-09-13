from __future__ import annotations

import math

import pandas as pd


_EVENT_COLUMNS = [
    "EntryPrice",
    "ExitPrice",
    "PartialExitPrice",
    "StopHitPrice",
    "InitialStopPoint",
    "ActiveStop",
]


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


def build_operational_chart_frame(
    df: pd.DataFrame,
    trades: pd.DataFrame | None,
    equity_curve: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Combine OHLC, trade events and stop levels for the backtest chart.

    The chart shows only executed events. When an engine exposes a dynamic stop
    series (currently ``TrailingStop``), it is used directly. Other engines fall
    back to the technical stop recorded at entry for the duration of each trade.
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
        initial_stop = _first_finite(
            trade,
            ["InitialStop", "InitialStopPrice", "StopPrice"],
        )

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
            if "stop" in reason or "breakeven" in reason:
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


def operational_chart_spec() -> dict:
    """Vega-Lite spec for candlesticks plus executed entries, exits and stops."""
    price_tooltip = [
        {"field": "Date", "type": "temporal", "title": "Data"},
        {"field": "Open", "type": "quantitative", "title": "Abertura", "format": ".2f"},
        {"field": "High", "type": "quantitative", "title": "Máxima", "format": ".2f"},
        {"field": "Low", "type": "quantitative", "title": "Mínima", "format": ".2f"},
        {"field": "Close", "type": "quantitative", "title": "Fechamento", "format": ".2f"},
    ]

    return {
        "height": 540,
        "encoding": {
            "x": {
                "field": "Date",
                "type": "temporal",
                "axis": {"title": None, "format": "%d/%m/%Y"},
            }
        },
        "layer": [
            {
                "mark": {"type": "rule", "color": "#64748b", "strokeWidth": 1},
                "encoding": {
                    "y": {"field": "Low", "type": "quantitative", "title": "Preço (R$)", "scale": {"zero": False}},
                    "y2": {"field": "High"},
                },
            },
            {
                "mark": {"type": "bar", "size": 5},
                "encoding": {
                    "y": {"field": "Open", "type": "quantitative", "scale": {"zero": False}},
                    "y2": {"field": "Close"},
                    "color": {
                        "condition": {"test": "datum.Close >= datum.Open", "value": "#16a34a"},
                        "value": "#dc2626",
                    },
                    "tooltip": price_tooltip,
                },
            },
            {
                "transform": [{"filter": "isValid(datum.ActiveStop)"}],
                "mark": {"type": "line", "color": "#f59e0b", "strokeWidth": 2, "strokeDash": [7, 5]},
                "encoding": {
                    "y": {"field": "ActiveStop", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Data"},
                        {"field": "ActiveStop", "type": "quantitative", "title": "Stop vigente", "format": ".2f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "isValid(datum.InitialStopPoint)"}],
                "mark": {"type": "point", "shape": "square", "filled": True, "size": 80, "color": "#f59e0b"},
                "encoding": {
                    "y": {"field": "InitialStopPoint", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Data"},
                        {"field": "InitialStopPoint", "type": "quantitative", "title": "Stop inicial", "format": ".2f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "isValid(datum.EntryPrice)"}],
                "mark": {"type": "point", "shape": "triangle-up", "filled": True, "size": 170, "color": "#00a152"},
                "encoding": {
                    "y": {"field": "EntryPrice", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Entrada"},
                        {"field": "EntryPrice", "type": "quantitative", "title": "Preço de entrada", "format": ".2f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "isValid(datum.PartialExitPrice)"}],
                "mark": {"type": "point", "shape": "diamond", "filled": True, "size": 130, "color": "#7c3aed"},
                "encoding": {
                    "y": {"field": "PartialExitPrice", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Saída parcial"},
                        {"field": "PartialExitPrice", "type": "quantitative", "title": "Preço", "format": ".2f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "isValid(datum.ExitPrice)"}],
                "mark": {"type": "point", "shape": "triangle-down", "filled": True, "size": 170, "color": "#2563eb"},
                "encoding": {
                    "y": {"field": "ExitPrice", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Saída"},
                        {"field": "ExitPrice", "type": "quantitative", "title": "Preço de saída", "format": ".2f"},
                    ],
                },
            },
            {
                "transform": [{"filter": "isValid(datum.StopHitPrice)"}],
                "mark": {"type": "point", "shape": "cross", "filled": True, "size": 220, "strokeWidth": 3, "color": "#b91c1c"},
                "encoding": {
                    "y": {"field": "StopHitPrice", "type": "quantitative", "scale": {"zero": False}},
                    "tooltip": [
                        {"field": "Date", "type": "temporal", "title": "Stop acionado"},
                        {"field": "StopHitPrice", "type": "quantitative", "title": "Preço", "format": ".2f"},
                    ],
                },
            },
        ],
        "config": {
            "view": {"stroke": None},
            "axis": {"gridColor": "#e2e8f0", "labelColor": "#475569", "titleColor": "#475569"},
        },
    }
