from __future__ import annotations

import math

import pandas as pd

from indicators import true_range
from .engine import BacktestConfig, BacktestResult
from .metrics import compute_metrics


ATR_PERIOD = 20
ATR_MULTIPLIER = 2.0


def _buy_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 + float(slippage_bps) / 10_000.0)


def _sell_price(raw: float, slippage_bps: float) -> float:
    return float(raw) * (1.0 - float(slippage_bps) / 10_000.0)


def _atr_sma(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """ATR com média aritmética do True Range, conforme especificação do setup."""
    return true_range(df).rolling(period, min_periods=period).mean()


def run_landry_adjusted_backtest(
    df: pd.DataFrame,
    orders: pd.DataFrame,
    config: BacktestConfig | None = None,
    *,
    atr_period: int = ATR_PERIOD,
    atr_multiplier: float = ATR_MULTIPLIER,
) -> BacktestResult:
    """Backtest do Dave Landry ajustado de compra com trailing Stop ATR.

    A ordem de entrada só é válida no candle imediatamente posterior ao sinal.
    No candle de entrada vale apenas o stop inicial do setup. A partir do candle
    seguinte, o stop efetivo passa a ser o maior entre o stop já vigente e:

        maior máxima favorável desde a entrada - atr_multiplier * ATR_SMA(atr_period)

    O ATR e a máxima usados no stop de cada candle vêm apenas de candles já
    encerrados, evitando look-ahead. O trailing stop nunca recua.
    """
    cfg = config or BacktestConfig()
    if cfg.initial_capital <= 0:
        raise ValueError("initial_capital deve ser positivo.")
    if not 0 < cfg.position_size_pct <= 1:
        raise ValueError("position_size_pct deve estar entre 0 e 1.")
    if cfg.commission_bps < 0 or cfg.slippage_bps < 0:
        raise ValueError("Custos e slippage não podem ser negativos.")
    if atr_period < 1:
        raise ValueError("atr_period deve ser >= 1.")
    if atr_multiplier <= 0:
        raise ValueError("atr_multiplier deve ser positivo.")

    required = ["Open", "High", "Low", "Close"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")
    if df.empty:
        raise ValueError("Histórico vazio.")

    df = df.copy().sort_index()
    orders = orders.copy() if orders is not None else pd.DataFrame()
    if not orders.empty:
        required_orders = ["ActiveDate", "Side", "TriggerPrice", "StopPrice"]
        missing_orders = [c for c in required_orders if c not in orders.columns]
        if missing_orders:
            raise ValueError(f"Colunas de ordens ausentes: {', '.join(missing_orders)}")
        orders["ActiveDate"] = pd.to_datetime(orders["ActiveDate"])
        if "SignalDate" in orders.columns:
            orders["SignalDate"] = pd.to_datetime(orders["SignalDate"])
        orders = orders.sort_values(["ActiveDate", "OrderId"], kind="stable").reset_index(drop=True)
        bad = set(orders["Side"].dropna().astype(str)) - {"long"}
        if bad:
            raise ValueError("Dave Landry ajustado suporta apenas compra/long.")

    by_date = {
        date: group
        for date, group in orders.groupby("ActiveDate", sort=False)
    } if not orders.empty else {}

    atr = _atr_sma(df, atr_period)
    commission_rate = cfg.commission_bps / 10_000.0
    cash = float(cfg.initial_capital)
    qty = 0
    entry_price: float | None = None
    entry_date = None
    entry_idx: int | None = None
    entry_total_cost: float | None = None
    initial_stop: float | None = None
    trailing_stop: float | None = None
    highest_high: float | None = None
    entry_order_id: str | None = None
    entry_setup: str | None = None

    equity_rows: list[dict] = []
    trades: list[dict] = []

    def equity_at(mark: float) -> float:
        return cash + qty * mark

    def close_position(date, raw_price: float, reason: str) -> None:
        nonlocal cash, qty, entry_price, entry_date, entry_idx, entry_total_cost
        nonlocal initial_stop, trailing_stop, highest_high, entry_order_id, entry_setup
        if qty <= 0 or entry_price is None or entry_total_cost is None:
            return

        px = _sell_price(raw_price, cfg.slippage_bps)
        gross = qty * px
        exit_commission = gross * commission_rate
        proceeds = gross - exit_commission
        cash += proceeds
        pnl = proceeds - entry_total_cost
        return_pct = pnl / entry_total_cost * 100.0 if entry_total_cost else float("nan")
        trades.append(
            {
                "EntryDate": entry_date,
                "ExitDate": date,
                "Side": "long",
                "Setup": entry_setup,
                "OrderId": entry_order_id,
                "EntryPrice": float(entry_price),
                "ExitPrice": float(px),
                "InitialStop": None if initial_stop is None else float(initial_stop),
                "FinalStop": None if trailing_stop is None else float(trailing_stop),
                "ATRPeriod": int(atr_period),
                "ATRMultiplier": float(atr_multiplier),
                "Quantity": int(qty),
                "PnL": float(pnl),
                "ReturnPct": float(return_pct),
                "ExitReason": reason,
            }
        )
        qty = 0
        entry_price = None
        entry_date = None
        entry_idx = None
        entry_total_cost = None
        initial_stop = None
        trailing_stop = None
        highest_high = None
        entry_order_id = None
        entry_setup = None

    def open_position(i: int, date, order: pd.Series, raw_price: float, high_px: float) -> None:
        nonlocal cash, qty, entry_price, entry_date, entry_idx, entry_total_cost
        nonlocal initial_stop, trailing_stop, highest_high, entry_order_id, entry_setup

        px = _buy_price(raw_price, cfg.slippage_bps)
        budget = equity_at(raw_price) * cfg.position_size_pct
        per_share_cash = px * (1.0 + commission_rate)
        shares = math.floor(budget / per_share_cash) if per_share_cash > 0 else 0
        if shares <= 0:
            return

        gross = shares * px
        entry_commission = gross * commission_rate
        total_cost = gross + entry_commission
        cash -= total_cost
        qty = int(shares)
        entry_price = float(px)
        entry_date = date
        entry_idx = int(i)
        entry_total_cost = float(total_cost)
        initial_stop = float(order["StopPrice"])
        trailing_stop = float(initial_stop)
        highest_high = float(high_px)
        entry_order_id = str(order.get("OrderId", ""))
        entry_setup = str(order.get("Setup", "landry_adjusted_buy"))

    for i, (date, row) in enumerate(df.iterrows()):
        open_px = float(row["Open"])
        high_px = float(row["High"])
        low_px = float(row["Low"])
        close_px = float(row["Close"])

        # A partir do candle seguinte ao da entrada, calcula o stop usando apenas
        # dados que já estavam fechados antes da abertura deste candle.
        if qty > 0 and entry_idx is not None and i > entry_idx:
            prev_i = i - 1
            if highest_high is None:
                highest_high = float(df["High"].iloc[entry_idx:prev_i + 1].astype(float).max())
            else:
                highest_high = max(highest_high, float(df["High"].iloc[prev_i]))
            atr_prev = atr.iloc[prev_i]
            if not pd.isna(atr_prev):
                candidate = float(highest_high) - float(atr_multiplier) * float(atr_prev)
                trailing_stop = max(float(trailing_stop), candidate) if trailing_stop is not None else candidate

        # Enquanto não há posição, somente ordens cujo ActiveDate é este candle
        # podem entrar. Assim o gatilho expira automaticamente após 1 candle.
        if qty == 0:
            day_orders = by_date.get(pd.Timestamp(date))
            if day_orders is not None:
                for _, order in day_orders.iterrows():
                    trigger = float(order["TriggerPrice"])
                    if open_px >= trigger:
                        open_position(i, date, order, open_px, high_px)
                        break
                    if high_px >= trigger:
                        open_position(i, date, order, trigger, high_px)
                        break

        # No candle da entrada trailing_stop == initial_stop. Só no candle seguinte
        # o bloco acima pode elevar o stop pelo ATR.
        if qty > 0 and trailing_stop is not None:
            stop_level = float(trailing_stop)
            using_atr = initial_stop is not None and stop_level > float(initial_stop) + 1e-12
            if open_px <= stop_level:
                close_position(date, open_px, "atr_stop_gap" if using_atr else "initial_stop_gap")
            elif qty > 0 and low_px <= stop_level:
                close_position(date, stop_level, "atr_stop" if using_atr else "initial_stop")

        # Se a posição sobreviveu ao candle, a máxima atual só poderá influenciar
        # o stop a partir do próximo candle.
        if qty > 0:
            highest_high = high_px if highest_high is None else max(float(highest_high), high_px)

        equity_rows.append(
            {
                "Date": date,
                "Cash": cash,
                "PositionQty": qty,
                "Close": close_px,
                "Equity": equity_at(close_px),
                "ATR20_SMA": None if pd.isna(atr.iloc[i]) else float(atr.iloc[i]),
                "TrailingStop": None if trailing_stop is None else float(trailing_stop),
            }
        )

    if qty > 0 and cfg.close_at_end:
        last_date = df.index[-1]
        close_position(last_date, float(df["Close"].iloc[-1]), "end_of_test")
        equity_rows[-1]["Cash"] = cash
        equity_rows[-1]["PositionQty"] = 0
        equity_rows[-1]["Equity"] = cash
        equity_rows[-1]["TrailingStop"] = None

    equity_curve = pd.DataFrame(equity_rows).set_index("Date")
    trades_df = pd.DataFrame(trades)
    metrics = compute_metrics(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_capital=cfg.initial_capital,
        periods_per_year=cfg.periods_per_year,
    )
    return BacktestResult(equity_curve=equity_curve, trades=trades_df, metrics=metrics)
