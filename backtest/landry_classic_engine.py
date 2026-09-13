from __future__ import annotations

import math

import pandas as pd

from .engine import BacktestConfig, BacktestResult
from .metrics import compute_metrics
from .order_engine import _normalize_orders, _buy_price, _sell_price


def run_landry_classic_backtest(
    df: pd.DataFrame,
    orders: pd.DataFrame,
    exit_signal: pd.Series | None = None,
    config: BacktestConfig | None = None,
    *,
    same_bar_policy: str = "conservative",
    partial_fraction: float = 0.50,
    trailing_bars: int = 2,
    tick_size: float = 0.01,
) -> BacktestResult:
    """Run deterministic Dave Landry-style trade management.

    Entry orders are supplied by ``compile_setup_orders``. Management is modeled
    as: initial technical stop, 50% realization at +1R/-1R, stop on the runner
    moved to breakeven, then a trailing stop based only on the previous N fully
    closed bars. This trailing convention is an explicit backtest convention for
    Landry's discretionary runner management; it is not presented as a verbatim
    mechanical rule from the author.
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
    if not 0 < partial_fraction < 1:
        raise ValueError("partial_fraction deve estar entre 0 e 1.")
    if trailing_bars < 1:
        raise ValueError("trailing_bars deve ser >= 1.")
    if tick_size < 0:
        raise ValueError("tick_size não pode ser negativo.")

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
    initial_qty = 0
    entry_price: float | None = None
    entry_date = None
    initial_stop: float | None = None
    current_stop: float | None = None
    entry_setup: str | None = None
    entry_order_id: str | None = None
    trade_cashflow = 0.0
    entry_commission = 0.0
    partial_taken = False
    partial_date = None
    partial_price: float | None = None
    partial_qty = 0
    partial_commission = 0.0
    partial_bar_index: int | None = None
    pending_exit = False

    equity_rows: list[dict] = []
    trades: list[dict] = []

    def equity_at(mark: float) -> float:
        if qty <= 0 or side is None:
            return cash
        if side == "long":
            return cash + qty * mark
        return cash - qty * mark

    def transact_exit(raw_price: float, shares: int) -> tuple[float, float, float]:
        nonlocal cash, trade_cashflow
        if side is None or shares <= 0:
            return float(raw_price), 0.0, 0.0
        if side == "long":
            px = _sell_price(raw_price, cfg.slippage_bps)
            gross = shares * px
            commission = gross * commission_rate
            flow = gross - commission
            cash += flow
        else:
            px = _buy_price(raw_price, cfg.slippage_bps)
            gross = shares * px
            commission = gross * commission_rate
            flow = -(gross + commission)
            cash += flow
        trade_cashflow += flow
        return float(px), float(commission), float(flow)

    def finalize_trade(date, raw_price: float, reason: str) -> None:
        nonlocal cash, side, qty, initial_qty, entry_price, entry_date, initial_stop, current_stop
        nonlocal entry_setup, entry_order_id, trade_cashflow, entry_commission, partial_taken
        nonlocal partial_date, partial_price, partial_qty, partial_commission, partial_bar_index
        if qty <= 0 or side is None or entry_price is None or initial_qty <= 0:
            return
        remaining_before = qty
        px, exit_commission, _ = transact_exit(raw_price, remaining_before)
        qty = 0
        pnl = float(trade_cashflow)
        base = initial_qty * entry_price + entry_commission
        return_pct = pnl / base * 100.0 if base else float("nan")
        risk_per_share = abs(entry_price - initial_stop) if initial_stop is not None else float("nan")
        risk_cash = initial_qty * risk_per_share if math.isfinite(risk_per_share) else float("nan")
        r_multiple = pnl / risk_cash if risk_cash and math.isfinite(risk_cash) else float("nan")
        trades.append(
            {
                "EntryDate": entry_date,
                "ExitDate": date,
                "Side": side,
                "Setup": entry_setup,
                "OrderId": entry_order_id,
                "EntryPrice": float(entry_price),
                "InitialStopPrice": float(initial_stop) if initial_stop is not None else None,
                "Quantity": int(initial_qty),
                "PartialExitDate": partial_date,
                "PartialExitPrice": partial_price,
                "PartialQuantity": int(partial_qty),
                "FinalExitPrice": float(px),
                "FinalQuantity": int(remaining_before),
                "PnL": pnl,
                "ReturnPct": float(return_pct),
                "RMultiple": float(r_multiple),
                "ExitReason": reason,
                "EntryCommission": float(entry_commission),
                "PartialCommission": float(partial_commission),
                "FinalCommission": float(exit_commission),
            }
        )
        side = None
        initial_qty = 0
        entry_price = None
        entry_date = None
        initial_stop = None
        current_stop = None
        entry_setup = None
        entry_order_id = None
        trade_cashflow = 0.0
        entry_commission = 0.0
        partial_taken = False
        partial_date = None
        partial_price = None
        partial_qty = 0
        partial_commission = 0.0
        partial_bar_index = None

    def open_position(date, order: pd.Series, raw_price: float) -> None:
        nonlocal cash, side, qty, initial_qty, entry_price, entry_date, initial_stop, current_stop
        nonlocal entry_setup, entry_order_id, trade_cashflow, entry_commission
        order_side = str(order["Side"])
        px = _buy_price(raw_price, cfg.slippage_bps) if order_side == "long" else _sell_price(raw_price, cfg.slippage_bps)
        budget = equity_at(float(raw_price)) * cfg.position_size_pct
        per_share = px * (1.0 + commission_rate)
        shares = math.floor(budget / per_share) if per_share > 0 else 0
        if shares <= 0:
            return
        raw_stop = order.get("StopPrice")
        stop = None if pd.isna(raw_stop) else float(raw_stop)
        if stop is None or (order_side == "long" and stop >= px) or (order_side == "short" and stop <= px):
            return

        gross = shares * px
        commission = gross * commission_rate
        if order_side == "long":
            flow = -(gross + commission)
        else:
            flow = gross - commission
        cash += flow

        side = order_side
        qty = int(shares)
        initial_qty = int(shares)
        entry_price = float(px)
        entry_date = date
        initial_stop = stop
        current_stop = stop
        entry_setup = None if pd.isna(order.get("Setup")) else str(order.get("Setup"))
        entry_order_id = None if pd.isna(order.get("OrderId")) else str(order.get("OrderId"))
        trade_cashflow = float(flow)
        entry_commission = float(commission)

    def cancellation_hit(order: pd.Series, open_px: float, high_px: float, low_px: float, *, intrabar: bool) -> bool:
        cb = order.get("CancelBelow")
        ca = order.get("CancelAbove")
        if cb is not None and not pd.isna(cb):
            level = float(cb)
            if open_px < level or (intrabar and low_px < level):
                return True
        if ca is not None and not pd.isna(ca):
            level = float(ca)
            if open_px > level or (intrabar and high_px > level):
                return True
        return False

    def take_partial(date, raw_price: float, bar_index: int) -> None:
        nonlocal qty, partial_taken, partial_date, partial_price, partial_qty, partial_commission
        nonlocal current_stop, partial_bar_index
        if qty <= 0 or entry_price is None or side is None:
            return
        shares = max(1, math.floor(initial_qty * partial_fraction))
        shares = min(shares, qty)
        px, commission, _ = transact_exit(raw_price, shares)
        qty -= shares
        partial_taken = True
        partial_date = date
        partial_price = float(px)
        partial_qty = int(shares)
        partial_commission = float(commission)
        partial_bar_index = bar_index
        current_stop = float(entry_price)

    for i, (date, row) in enumerate(df.iterrows()):
        open_px = float(row["Open"])
        high_px = float(row["High"])
        low_px = float(row["Low"])
        close_px = float(row["Close"])

        if qty > 0 and pending_exit:
            finalize_trade(date, open_px, "signal")
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

        if qty > 0 and side is not None and entry_price is not None and current_stop is not None:
            if partial_taken and partial_bar_index is not None and i > partial_bar_index:
                start = max(0, i - trailing_bars)
                if side == "long":
                    candidate = float(df["Low"].iloc[start:i].min()) - tick_size
                    current_stop = max(float(current_stop), candidate, float(entry_price))
                else:
                    candidate = float(df["High"].iloc[start:i].max()) + tick_size
                    current_stop = min(float(current_stop), candidate, float(entry_price))

            risk = abs(float(entry_price) - float(initial_stop)) if initial_stop is not None else None
            target = None
            if risk is not None and risk > 0:
                target = float(entry_price) + risk if side == "long" else float(entry_price) - risk

            if side == "long":
                if open_px <= current_stop:
                    finalize_trade(date, open_px, "stop_gap" if not partial_taken else "runner_stop_gap")
                elif not partial_taken and target is not None and open_px >= target:
                    take_partial(date, open_px, i)
                    if qty == 0:
                        # A one-share position cannot have a runner; register it as a complete 1R trade.
                        # Re-open a zero-quantity finalization is avoided by recording directly below.
                        pnl = float(trade_cashflow)
                        base = initial_qty * entry_price + entry_commission
                        risk_cash = initial_qty * abs(entry_price - initial_stop)
                        trades.append({
                            "EntryDate": entry_date, "ExitDate": date, "Side": side, "Setup": entry_setup,
                            "OrderId": entry_order_id, "EntryPrice": float(entry_price), "InitialStopPrice": float(initial_stop),
                            "Quantity": int(initial_qty), "PartialExitDate": partial_date, "PartialExitPrice": partial_price,
                            "PartialQuantity": int(partial_qty), "FinalExitPrice": partial_price, "FinalQuantity": 0,
                            "PnL": pnl, "ReturnPct": pnl / base * 100.0 if base else float("nan"),
                            "RMultiple": pnl / risk_cash if risk_cash else float("nan"), "ExitReason": "target_1R_full_due_size",
                            "EntryCommission": float(entry_commission), "PartialCommission": float(partial_commission), "FinalCommission": 0.0,
                        })
                        side = None
                        initial_qty = 0
                        entry_price = None
                        entry_date = None
                        initial_stop = None
                        current_stop = None
                        entry_setup = None
                        entry_order_id = None
                        trade_cashflow = 0.0
                        entry_commission = 0.0
                        partial_taken = False
                        partial_date = None
                        partial_price = None
                        partial_qty = 0
                        partial_commission = 0.0
                        partial_bar_index = None
                    elif low_px <= current_stop:
                        finalize_trade(date, current_stop, "runner_breakeven_same_bar")
                elif not partial_taken and low_px <= current_stop:
                    finalize_trade(date, current_stop, "stop")
                elif not partial_taken and target is not None and high_px >= target:
                    take_partial(date, target, i)
                    if qty > 0 and low_px <= current_stop:
                        finalize_trade(date, current_stop, "runner_breakeven_same_bar")
                elif partial_taken and low_px <= current_stop:
                    finalize_trade(date, current_stop, "runner_trailing_stop")
            else:
                if open_px >= current_stop:
                    finalize_trade(date, open_px, "stop_gap" if not partial_taken else "runner_stop_gap")
                elif not partial_taken and target is not None and open_px <= target:
                    take_partial(date, open_px, i)
                    if qty == 0:
                        pnl = float(trade_cashflow)
                        base = initial_qty * entry_price + entry_commission
                        risk_cash = initial_qty * abs(entry_price - initial_stop)
                        trades.append({
                            "EntryDate": entry_date, "ExitDate": date, "Side": side, "Setup": entry_setup,
                            "OrderId": entry_order_id, "EntryPrice": float(entry_price), "InitialStopPrice": float(initial_stop),
                            "Quantity": int(initial_qty), "PartialExitDate": partial_date, "PartialExitPrice": partial_price,
                            "PartialQuantity": int(partial_qty), "FinalExitPrice": partial_price, "FinalQuantity": 0,
                            "PnL": pnl, "ReturnPct": pnl / base * 100.0 if base else float("nan"),
                            "RMultiple": pnl / risk_cash if risk_cash else float("nan"), "ExitReason": "target_1R_full_due_size",
                            "EntryCommission": float(entry_commission), "PartialCommission": float(partial_commission), "FinalCommission": 0.0,
                        })
                        side = None
                        initial_qty = 0
                        entry_price = None
                        entry_date = None
                        initial_stop = None
                        current_stop = None
                        entry_setup = None
                        entry_order_id = None
                        trade_cashflow = 0.0
                        entry_commission = 0.0
                        partial_taken = False
                        partial_date = None
                        partial_price = None
                        partial_qty = 0
                        partial_commission = 0.0
                        partial_bar_index = None
                    elif high_px >= current_stop:
                        finalize_trade(date, current_stop, "runner_breakeven_same_bar")
                elif not partial_taken and high_px >= current_stop:
                    finalize_trade(date, current_stop, "stop")
                elif not partial_taken and target is not None and low_px <= target:
                    take_partial(date, target, i)
                    if qty > 0 and high_px >= current_stop:
                        finalize_trade(date, current_stop, "runner_breakeven_same_bar")
                elif partial_taken and high_px >= current_stop:
                    finalize_trade(date, current_stop, "runner_trailing_stop")

        equity_rows.append(
            {
                "Date": date,
                "Cash": cash,
                "PositionQty": qty if side != "short" else -qty,
                "Close": close_px,
                "Equity": equity_at(close_px),
            }
        )

        if i < len(df) - 1 and qty > 0 and bool(exit_signal.loc[date]):
            pending_exit = True

    if qty > 0 and cfg.close_at_end:
        last_date = df.index[-1]
        finalize_trade(last_date, float(df["Close"].iloc[-1]), "end_of_test")
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
