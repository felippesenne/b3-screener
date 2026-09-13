from __future__ import annotations

from dataclasses import dataclass

import math
import pandas as pd

from .metrics import compute_metrics


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    position_size_pct: float = 1.0
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    close_at_end: bool = True
    periods_per_year: int = 252


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict


def _validate(df: pd.DataFrame, entry_signal: pd.Series, exit_signal: pd.Series | None) -> tuple[pd.Series, pd.Series]:
    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Histórico vazio.")
    if not df.index.is_monotonic_increasing:
        df.sort_index(inplace=True)

    entry = entry_signal.reindex(df.index).fillna(False).astype(bool)
    exit_ = (
        exit_signal.reindex(df.index).fillna(False).astype(bool)
        if exit_signal is not None
        else pd.Series(False, index=df.index, dtype=bool)
    )
    return entry, exit_


def _buy_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 + float(slippage_bps) / 10_000.0)


def _sell_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 - float(slippage_bps) / 10_000.0)


def run_backtest(
    df: pd.DataFrame,
    entry_signal: pd.Series,
    exit_signal: pd.Series | None = None,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Long-only event-driven backtest with next-open execution.

    Signals are read at bar close and become executable only at the next bar open,
    preventing the most common look-ahead error. Stops and targets are evaluated
    after the open on each bar. If the market gaps beyond a stop/target, execution
    occurs at the opening price rather than at an impossible historical level.
    """
    cfg = config or BacktestConfig()
    if cfg.initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo.")
    if not 0 < cfg.position_size_pct <= 1:
        raise ValueError("position_size_pct deve estar entre 0 e 1.")
    if cfg.commission_bps < 0 or cfg.slippage_bps < 0:
        raise ValueError("Custos e slippage não podem ser negativos.")

    df = df.copy()
    entry_signal, exit_signal = _validate(df, entry_signal, exit_signal)

    commission_rate = cfg.commission_bps / 10_000.0
    cash = float(cfg.initial_capital)
    qty = 0
    entry_price = None
    entry_date = None
    entry_total_cost = None
    pending_entry = False
    pending_exit = False

    equity_rows: list[dict] = []
    trades: list[dict] = []

    def close_position(date, raw_price: float, reason: str) -> None:
        nonlocal cash, qty, entry_price, entry_date, entry_total_cost
        if qty <= 0:
            return
        px = _sell_price(raw_price, cfg.slippage_bps)
        gross = qty * px
        exit_commission = gross * commission_rate
        proceeds = gross - exit_commission
        cash += proceeds
        pnl = proceeds - float(entry_total_cost)
        return_pct = pnl / float(entry_total_cost) * 100.0 if entry_total_cost else float("nan")
        trades.append(
            {
                "EntryDate": entry_date,
                "ExitDate": date,
                "EntryPrice": float(entry_price),
                "ExitPrice": float(px),
                "Quantity": int(qty),
                "PnL": float(pnl),
                "ReturnPct": float(return_pct),
                "ExitReason": reason,
            }
        )
        qty = 0
        entry_price = None
        entry_date = None
        entry_total_cost = None

    for i, (date, row) in enumerate(df.iterrows()):
        open_px = float(row["Open"])
        high_px = float(row["High"])
        low_px = float(row["Low"])
        close_px = float(row["Close"])

        # Orders generated at the previous close execute at this bar's open.
        if qty > 0 and pending_exit:
            close_position(date, open_px, "signal")
        pending_exit = False

        if qty == 0 and pending_entry:
            px = _buy_price(open_px, cfg.slippage_bps)
            budget = cash * cfg.position_size_pct
            per_share_cash = px * (1.0 + commission_rate)
            shares = math.floor(budget / per_share_cash) if per_share_cash > 0 else 0
            if shares > 0:
                gross = shares * px
                entry_commission = gross * commission_rate
                total_cost = gross + entry_commission
                cash -= total_cost
                qty = int(shares)
                entry_price = float(px)
                entry_date = date
                entry_total_cost = float(total_cost)
        pending_entry = False

        # Intrabar protective orders. Gap logic uses the opening price.
        if qty > 0 and entry_price is not None:
            stop_level = entry_price * (1.0 - cfg.stop_loss_pct) if cfg.stop_loss_pct is not None else None
            target_level = entry_price * (1.0 + cfg.take_profit_pct) if cfg.take_profit_pct is not None else None

            if stop_level is not None and open_px <= stop_level:
                close_position(date, open_px, "stop_gap")
            elif target_level is not None and open_px >= target_level:
                close_position(date, open_px, "target_gap")
            elif qty > 0 and stop_level is not None and low_px <= stop_level:
                close_position(date, stop_level, "stop")
            elif qty > 0 and target_level is not None and high_px >= target_level:
                close_position(date, target_level, "target")

        equity = cash + qty * close_px
        equity_rows.append({"Date": date, "Cash": cash, "PositionQty": qty, "Close": close_px, "Equity": equity})

        # Current bar signals are only actionable on the next bar.
        if i < len(df) - 1:
            if qty > 0 and bool(exit_signal.loc[date]):
                pending_exit = True
            elif qty == 0 and bool(entry_signal.loc[date]):
                pending_entry = True

    if qty > 0 and cfg.close_at_end:
        last_date = df.index[-1]
        close_position(last_date, float(df["Close"].iloc[-1]), "end_of_test")
        equity_rows[-1]["Cash"] = cash
        equity_rows[-1]["PositionQty"] = 0
        equity_rows[-1]["Equity"] = cash

    equity_curve = pd.DataFrame(equity_rows).set_index("Date")
    trades_df = pd.DataFrame(trades)
    metrics = compute_metrics(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_capital=cfg.initial_capital,
        periods_per_year=cfg.periods_per_year,
    )
    return BacktestResult(equity_curve=equity_curve, trades=trades_df, metrics=metrics)
