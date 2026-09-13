from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd

from .engine import BacktestConfig, BacktestResult
from .metrics import compute_metrics


ORDER_COLUMNS = [
    "ActiveDate",
    "OrderId",
    "Setup",
    "Side",
    "SignalDate",
    "TriggerPrice",
    "StopPrice",
    "CancelBelow",
    "CancelAbove",
]


def _empty_orders() -> pd.DataFrame:
    return pd.DataFrame(columns=ORDER_COLUMNS)


def _normalize_orders(df: pd.DataFrame, orders: pd.DataFrame | None) -> pd.DataFrame:
    if orders is None or orders.empty:
        return _empty_orders()
    missing = [c for c in ("ActiveDate", "Side", "TriggerPrice") if c not in orders.columns]
    if missing:
        raise ValueError(f"Colunas de ordens ausentes: {', '.join(missing)}")
    out = orders.copy()
    out["ActiveDate"] = pd.to_datetime(out["ActiveDate"])
    if "SignalDate" in out.columns:
        out["SignalDate"] = pd.to_datetime(out["SignalDate"])
    for col in ORDER_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[ORDER_COLUMNS]
    out["OrderId"] = out["OrderId"].fillna("").astype(str)
    out = out.sort_values(["ActiveDate", "OrderId"], kind="stable").reset_index(drop=True)
    bad_sides = sorted(set(out["Side"].dropna()) - {"long", "short"})
    if bad_sides:
        raise ValueError(f"Lados de ordem inválidos: {bad_sides}")
    return out


def _buy_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 + float(slippage_bps) / 10_000.0)


def _sell_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 - float(slippage_bps) / 10_000.0)


def run_order_backtest(
    df: pd.DataFrame,
    orders: pd.DataFrame,
    exit_signal: pd.Series | None = None,
    config: BacktestConfig | None = None,
    *,
    same_bar_policy: str = "conservative",
) -> BacktestResult:
    """Backtest stop-entry orders with technical stops for long and short trades.

    Each row in ``orders`` is an order active only on ``ActiveDate``. Strategy
    adapters express persistence by emitting one row for every bar in which the
    order remains valid. This keeps cancellation logic outside the portfolio
    engine and makes setup semantics testable.

    ``same_bar_policy='conservative'`` treats an intrabar cancellation threshold
    as occurring before an intrabar trigger when OHLC data cannot reveal the
    sequence. Opening gaps are unambiguous and are processed first.
    """
    cfg = config or BacktestConfig()
    if cfg.initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo.")
    if not 0 < cfg.position_size_pct <= 1:
        raise ValueError("position_size_pct deve estar entre 0 e 1.")
    if cfg.commission_bps < 0 or cfg.slippage_bps < 0:
        raise ValueError("Custos e slippage não podem ser negativos.")
    if same_bar_policy not in {"conservative", "trigger_first"}:
        raise ValueError("same_bar_policy deve ser 'conservative' ou 'trigger_first'.")

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Histórico vazio.")

    df = df.copy().sort_index()
    orders = _normalize_orders(df, orders)
    by_date = {date: group for date, group in orders.groupby("ActiveDate", sort=False)}
    exit_signal = (
        exit_signal.reindex(df.index).fillna(False).astype(bool)
        if exit_signal is not None
        else pd.Series(False, index=df.index, dtype=bool)
    )

    commission_rate = cfg.commission_bps / 10_000.0
    cash = float(cfg.initial_capital)
    side: str | None = None
    qty = 0
    entry_price: float | None = None
    entry_date = None
    entry_commission = 0.0
    entry_stop: float | None = None
    entry_setup: str | None = None
    entry_order_id: str | None = None
    pending_exit = False

    equity_rows: list[dict] = []
    trades: list[dict] = []

    def equity_at(mark: float) -> float:
        if qty <= 0 or side is None:
            return cash
        if side == "long":
            return cash + qty * mark
        return cash - qty * mark

    def close_position(date, raw_price: float, reason: str) -> None:
        nonlocal cash, side, qty, entry_price, entry_date, entry_commission, entry_stop, entry_setup, entry_order_id
        if qty <= 0 or side is None or entry_price is None:
            return
        if side == "long":
            px = _sell_price(raw_price, cfg.slippage_bps)
            gross = qty * px
            exit_commission = gross * commission_rate
            cash += gross - exit_commission
            pnl = qty * (px - entry_price) - entry_commission - exit_commission
        else:
            px = _buy_price(raw_price, cfg.slippage_bps)
            gross = qty * px
            exit_commission = gross * commission_rate
            cash -= gross + exit_commission
            pnl = qty * (entry_price - px) - entry_commission - exit_commission

        base = qty * entry_price + entry_commission
        return_pct = pnl / base * 100.0 if base else float("nan")
        trades.append(
            {
                "EntryDate": entry_date,
                "ExitDate": date,
                "Side": side,
                "Setup": entry_setup,
                "OrderId": entry_order_id,
                "EntryPrice": float(entry_price),
                "ExitPrice": float(px),
                "StopPrice": float(entry_stop) if entry_stop is not None else None,
                "Quantity": int(qty),
                "PnL": float(pnl),
                "ReturnPct": float(return_pct),
                "ExitReason": reason,
            }
        )
        side = None
        qty = 0
        entry_price = None
        entry_date = None
        entry_commission = 0.0
        entry_stop = None
        entry_setup = None
        entry_order_id = None

    def open_position(date, order: pd.Series, raw_price: float) -> None:
        nonlocal cash, side, qty, entry_price, entry_date, entry_commission, entry_stop, entry_setup, entry_order_id
        order_side = str(order["Side"])
        px = _buy_price(raw_price, cfg.slippage_bps) if order_side == "long" else _sell_price(raw_price, cfg.slippage_bps)
        budget = equity_at(float(raw_price)) * cfg.position_size_pct
        per_share = px * (1.0 + commission_rate)
        shares = math.floor(budget / per_share) if per_share > 0 else 0
        if shares <= 0:
            return
        gross = shares * px
        commission = gross * commission_rate
        if order_side == "long":
            cash -= gross + commission
        else:
            cash += gross - commission

        side = order_side
        qty = int(shares)
        entry_price = float(px)
        entry_date = date
        entry_commission = float(commission)
        raw_stop = order.get("StopPrice")
        entry_stop = None if pd.isna(raw_stop) else float(raw_stop)
        entry_setup = None if pd.isna(order.get("Setup")) else str(order.get("Setup"))
        entry_order_id = None if pd.isna(order.get("OrderId")) else str(order.get("OrderId"))

    def cancellation_hit(order: pd.Series, open_px: float, high_px: float, low_px: float, *, intrabar: bool) -> bool:
        cb = order.get("CancelBelow")
        ca = order.get("CancelAbove")
        if cb is not None and not pd.isna(cb):
            level = float(cb)
            if open_px < level:
                return True
            if intrabar and low_px < level:
                return True
        if ca is not None and not pd.isna(ca):
            level = float(ca)
            if open_px > level:
                return True
            if intrabar and high_px > level:
                return True
        return False

    for i, (date, row) in enumerate(df.iterrows()):
        open_px = float(row["Open"])
        high_px = float(row["High"])
        low_px = float(row["Low"])
        close_px = float(row["Close"])

        if qty > 0 and pending_exit:
            close_position(date, open_px, "signal")
        pending_exit = False

        if qty == 0:
            day_orders = by_date.get(pd.Timestamp(date))
            if day_orders is not None:
                for _, order in day_orders.iterrows():
                    order_side = str(order["Side"])
                    trigger = float(order["TriggerPrice"])

                    if cancellation_hit(order, open_px, high_px, low_px, intrabar=False):
                        continue
                    gap_trigger = (order_side == "long" and open_px >= trigger) or (order_side == "short" and open_px <= trigger)
                    if gap_trigger:
                        open_position(date, order, open_px)
                        break

                    intrabar_trigger = (order_side == "long" and high_px >= trigger) or (order_side == "short" and low_px <= trigger)
                    if not intrabar_trigger:
                        continue
                    if same_bar_policy == "conservative" and cancellation_hit(order, open_px, high_px, low_px, intrabar=True):
                        continue

                    open_position(date, order, trigger)
                    break

        if qty > 0 and side is not None and entry_price is not None:
            if entry_stop is not None:
                stop_level = entry_stop
            elif cfg.stop_loss_pct is not None:
                stop_level = (
                    entry_price * (1.0 - cfg.stop_loss_pct)
                    if side == "long"
                    else entry_price * (1.0 + cfg.stop_loss_pct)
                )
            else:
                stop_level = None

            target_level = None
            if cfg.take_profit_pct is not None:
                target_level = (
                    entry_price * (1.0 + cfg.take_profit_pct)
                    if side == "long"
                    else entry_price * (1.0 - cfg.take_profit_pct)
                )

            if side == "long":
                if stop_level is not None and open_px <= stop_level:
                    close_position(date, open_px, "stop_gap")
                elif target_level is not None and open_px >= target_level:
                    close_position(date, open_px, "target_gap")
                elif qty > 0 and stop_level is not None and low_px <= stop_level:
                    close_position(date, stop_level, "stop")
                elif qty > 0 and target_level is not None and high_px >= target_level:
                    close_position(date, target_level, "target")
            else:
                if stop_level is not None and open_px >= stop_level:
                    close_position(date, open_px, "stop_gap")
                elif target_level is not None and open_px <= target_level:
                    close_position(date, open_px, "target_gap")
                elif qty > 0 and stop_level is not None and high_px >= stop_level:
                    close_position(date, stop_level, "stop")
                elif qty > 0 and target_level is not None and low_px <= target_level:
                    close_position(date, target_level, "target")

        equity = equity_at(close_px)
        equity_rows.append(
            {
                "Date": date,
                "Cash": cash,
                "PositionQty": qty if side != "short" else -qty,
                "Close": close_px,
                "Equity": equity,
            }
        )

        if i < len(df) - 1 and qty > 0 and bool(exit_signal.loc[date]):
            pending_exit = True

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
