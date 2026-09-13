from __future__ import annotations

import math

import pandas as pd

from indicators import rsi_wilder
from .engine import BacktestConfig, BacktestResult
from .metrics import compute_metrics


SETUP_ID = "ifr2_ifr14_rolling_buy"


def _buy_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 + float(slippage_bps) / 10_000.0)


def _sell_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 - float(slippage_bps) / 10_000.0)


def _crosses_below(series: pd.Series, idx: int, level: float) -> bool:
    if idx <= 0:
        return False
    prev = series.iloc[idx - 1]
    now = series.iloc[idx]
    return pd.notna(prev) and pd.notna(now) and float(prev) >= level and float(now) < level


def _crosses_above(series: pd.Series, idx: int, level: float) -> bool:
    if idx <= 0:
        return False
    prev = series.iloc[idx - 1]
    now = series.iloc[idx]
    return pd.notna(prev) and pd.notna(now) and float(prev) <= level and float(now) > level


def run_ifr2_ifr14_rolling_backtest(
    df: pd.DataFrame,
    config: BacktestConfig | None = None,
    *,
    entry_rsi_period: int = 2,
    entry_rsi_level: float = 10.0,
    exit_rsi_period: int = 14,
    exit_rsi_level: float = 70.0,
    tick_size: float = 0.01,
) -> tuple[pd.DataFrame, BacktestResult]:
    """Backtest a long-only RSI setup with rolling stop-entry and stop-exit triggers.

    Entry semantics:
    - RSI(entry_rsi_period) crosses below entry_rsi_level on a bar close.
    - Starting on the next bar, buy on a break above the signal bar high + tick.
    - If not triggered, the next bar's trigger rolls down to that completed bar's high + tick.

    Exit semantics:
    - While long, RSI(exit_rsi_period) crosses above exit_rsi_level on a bar close.
    - Starting on the next bar, sell on a break below the signal bar low - tick.
    - If not triggered, the stop reference ratchets upward to the completed bar's low - tick.
      It is never loosened downward.

    Signals are evaluated only after the bar closes, so no current-bar high/low is used
    to create a trigger that could execute earlier in that same bar.
    """
    cfg = config or BacktestConfig()
    if df.empty:
        raise ValueError("Histórico vazio.")
    missing = [c for c in ("Open", "High", "Low", "Close") if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")
    if cfg.initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo.")
    if not 0 < cfg.position_size_pct <= 1:
        raise ValueError("position_size_pct deve estar entre 0 e 1.")
    if cfg.commission_bps < 0 or cfg.slippage_bps < 0:
        raise ValueError("Custos e slippage não podem ser negativos.")
    if entry_rsi_period < 1 or exit_rsi_period < 1:
        raise ValueError("Períodos de IFR devem ser positivos.")
    if tick_size < 0:
        raise ValueError("tick_size não pode ser negativo.")

    df = df.copy().sort_index()
    close = df["Close"].astype(float)
    rsi_entry = rsi_wilder(close, entry_rsi_period)
    rsi_exit = rsi_wilder(close, exit_rsi_period)

    commission_rate = cfg.commission_bps / 10_000.0
    cash = float(cfg.initial_capital)
    qty = 0
    entry_price: float | None = None
    entry_date = None
    entry_commission = 0.0
    entry_signal_date = None
    exit_signal_date = None

    pending_entry = False
    entry_trigger: float | None = None
    entry_reference_date = None

    pending_exit = False
    exit_trigger: float | None = None
    exit_reference_date = None

    order_rows: list[dict] = []
    equity_rows: list[dict] = []
    trades: list[dict] = []

    def equity_at(mark: float) -> float:
        return cash + qty * mark

    def open_position(date, raw_price: float) -> None:
        nonlocal cash, qty, entry_price, entry_date, entry_commission
        px = _buy_price(raw_price, cfg.slippage_bps)
        budget = cash * cfg.position_size_pct
        per_share = px * (1.0 + commission_rate)
        shares = math.floor(budget / per_share) if per_share > 0 else 0
        if shares <= 0:
            return
        gross = shares * px
        commission = gross * commission_rate
        cash -= gross + commission
        qty = int(shares)
        entry_price = float(px)
        entry_date = date
        entry_commission = float(commission)

    def close_position(date, raw_price: float, reason: str) -> None:
        nonlocal cash, qty, entry_price, entry_date, entry_commission
        nonlocal pending_exit, exit_trigger, exit_reference_date, exit_signal_date
        if qty <= 0 or entry_price is None:
            return
        px = _sell_price(raw_price, cfg.slippage_bps)
        gross = qty * px
        exit_commission = gross * commission_rate
        cash += gross - exit_commission
        pnl = qty * (px - entry_price) - entry_commission - exit_commission
        base = qty * entry_price + entry_commission
        trades.append(
            {
                "EntryDate": entry_date,
                "ExitDate": date,
                "Side": "long",
                "Setup": SETUP_ID,
                "EntrySignalDate": entry_signal_date,
                "ExitSignalDate": exit_signal_date,
                "EntryPrice": float(entry_price),
                "ExitPrice": float(px),
                "Quantity": int(qty),
                "PnL": float(pnl),
                "ReturnPct": float(pnl / base * 100.0) if base else float("nan"),
                "ExitReason": reason,
            }
        )
        qty = 0
        entry_price = None
        entry_date = None
        entry_commission = 0.0
        pending_exit = False
        exit_trigger = None
        exit_reference_date = None
        exit_signal_date = None

    for i, (date, row) in enumerate(df.iterrows()):
        open_px = float(row["Open"])
        high_px = float(row["High"])
        low_px = float(row["Low"])
        close_px = float(row["Close"])

        entered_today = False
        exited_today = False

        if qty > 0 and pending_exit and exit_trigger is not None:
            order_rows.append(
                {
                    "Phase": "exit",
                    "ActiveDate": date,
                    "SignalDate": exit_signal_date,
                    "ReferenceDate": exit_reference_date,
                    "TriggerPrice": float(exit_trigger),
                    "RSIPeriod": int(exit_rsi_period),
                    "RSILevel": float(exit_rsi_level),
                }
            )
            if open_px <= exit_trigger:
                close_position(date, open_px, "ifr14_exit_gap")
                exited_today = True
            elif low_px <= exit_trigger:
                close_position(date, exit_trigger, "ifr14_exit")
                exited_today = True

        if qty == 0 and pending_entry and entry_trigger is not None and not exited_today:
            order_rows.append(
                {
                    "Phase": "entry",
                    "ActiveDate": date,
                    "SignalDate": entry_signal_date,
                    "ReferenceDate": entry_reference_date,
                    "TriggerPrice": float(entry_trigger),
                    "RSIPeriod": int(entry_rsi_period),
                    "RSILevel": float(entry_rsi_level),
                }
            )
            if open_px >= entry_trigger:
                open_position(date, open_px)
                entered_today = qty > 0
            elif high_px >= entry_trigger:
                open_position(date, entry_trigger)
                entered_today = qty > 0
            if entered_today:
                pending_entry = False
                entry_trigger = None
                entry_reference_date = None

        equity_rows.append(
            {
                "Date": date,
                "Cash": float(cash),
                "PositionQty": int(qty),
                "Close": close_px,
                "Equity": float(equity_at(close_px)),
            }
        )

        # Close-of-bar state updates. All resulting triggers become active next bar.
        if qty > 0:
            if pending_exit and not exited_today:
                candidate = low_px - tick_size
                if exit_trigger is None:
                    exit_trigger = candidate
                else:
                    exit_trigger = max(float(exit_trigger), float(candidate))
                exit_reference_date = date
            elif not pending_exit and _crosses_above(rsi_exit, i, exit_rsi_level):
                pending_exit = True
                exit_signal_date = date
                exit_reference_date = date
                exit_trigger = low_px - tick_size
        else:
            if pending_entry and not entered_today:
                entry_trigger = high_px + tick_size
                entry_reference_date = date
            elif not pending_entry and _crosses_below(rsi_entry, i, entry_rsi_level):
                pending_entry = True
                entry_signal_date = date
                entry_reference_date = date
                entry_trigger = high_px + tick_size

    if qty > 0 and cfg.close_at_end:
        last_date = df.index[-1]
        close_position(last_date, float(df["Close"].iloc[-1]), "end_of_test")
        equity_rows[-1]["Cash"] = float(cash)
        equity_rows[-1]["PositionQty"] = 0
        equity_rows[-1]["Equity"] = float(cash)

    equity_curve = pd.DataFrame(equity_rows).set_index("Date")
    trades_df = pd.DataFrame(trades)
    orders_df = pd.DataFrame(
        order_rows,
        columns=[
            "Phase",
            "ActiveDate",
            "SignalDate",
            "ReferenceDate",
            "TriggerPrice",
            "RSIPeriod",
            "RSILevel",
        ],
    )
    metrics = compute_metrics(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_capital=cfg.initial_capital,
        periods_per_year=cfg.periods_per_year,
    )
    return orders_df, BacktestResult(equity_curve=equity_curve, trades=trades_df, metrics=metrics)
