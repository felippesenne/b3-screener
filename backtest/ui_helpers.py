from __future__ import annotations

import math

import pandas as pd

from indicators import resample_ohlcv
from .engine import BacktestConfig, BacktestResult
from .landry_classic_engine import run_landry_classic_backtest
from .landry_classic_setup import compile_landry_classic_orders
from .order_engine import run_order_backtest
from .setup_orders import compile_setup_orders
from .signals import compile_rules_signal


SETUP_LABELS = {
    "Larry Williams — Setup 9.1 Compra": "setup_91_buy",
    "Larry Williams — Setup 9.1 Venda": "setup_91_sell",
    "PFR — Compra": "pfr_buy",
    "PFR — Venda": "pfr_sell",
    "Setup 1-2-3 — Compra": "setup_123_buy",
    "Setup 1-2-3 — Venda": "setup_123_sell",
    "Dave Landry — Simple Pullback Clássico Compra": "landry_classic_buy",
    "Dave Landry — Simple Pullback Clássico Venda": "landry_classic_sell",
    "Dave Landry Simple — Compra (simplificado)": "landry_simple_buy",
    "Dave Landry Simple — Venda (simplificado)": "landry_simple_sell",
    "Dave Landry — Bow Tie Compra": "bowtie_buy",
    "Dave Landry — Bow Tie Venda": "bowtie_sell",
}

EXIT_LABELS = [
    "Somente stop técnico / alvo / fim do teste",
    "MME9 vira contra a posição",
    "Fechamento cruza a MME9 contra a posição",
    "Fechamento cruza a MME21 contra a posição",
    "IFR(2) retorna para 70/30",
    "IFR(2) retorna para 90/10",
]

PERIODS_PER_YEAR = {"Diário": 252, "Semanal": 52, "Mensal": 12}


def setup_side(setup_id: str) -> str:
    return "long" if setup_id.endswith("_buy") else "short"


def build_exit_rules(label: str, setup_id: str) -> list[dict] | None:
    side = setup_side(setup_id)
    price = {"kind": "PRICE", "field": "Close"}

    if label == EXIT_LABELS[0]:
        return None
    if label == "MME9 vira contra a posição":
        return [{"left": {"kind": "EMA", "period": 9}, "operator": "falling" if side == "long" else "rising"}]
    if label == "Fechamento cruza a MME9 contra a posição":
        return [{
            "left": price,
            "operator": "crosses_below" if side == "long" else "crosses_above",
            "right_kind": "indicator",
            "right": {"kind": "EMA", "period": 9},
        }]
    if label == "Fechamento cruza a MME21 contra a posição":
        return [{
            "left": price,
            "operator": "crosses_below" if side == "long" else "crosses_above",
            "right_kind": "indicator",
            "right": {"kind": "EMA", "period": 21},
        }]
    if label == "IFR(2) retorna para 70/30":
        return [{
            "left": {"kind": "RSI", "period": 2},
            "operator": ">" if side == "long" else "<",
            "right_kind": "value",
            "right_value": 70.0 if side == "long" else 30.0,
        }]
    if label == "IFR(2) retorna para 90/10":
        return [{
            "left": {"kind": "RSI", "period": 2},
            "operator": ">" if side == "long" else "<",
            "right_kind": "value",
            "right_value": 90.0 if side == "long" else 10.0,
        }]
    raise ValueError(f"Saída não suportada: {label}")


def run_setup_backtest_from_history(
    raw: pd.DataFrame,
    *,
    setup_id: str,
    timeframe: str,
    capital: float,
    position_size_pct: float,
    commission_bps: float,
    slippage_bps: float,
    take_profit_pct: float | None,
    exit_label: str,
    tick_size: float = 0.01,
    landry_valid_bars: int = 1,
    bowtie_transition_bars: int = 4,
    same_bar_policy: str = "conservative",
    landry_min_pullback_bars: int = 3,
    landry_max_pullback_bars: int = 7,
    landry_trend_lookback: int = 20,
    landry_trailing_bars: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, BacktestResult]:
    df = resample_ohlcv(raw, timeframe)
    if len(df) < 3:
        raise ValueError("Histórico insuficiente para backtest.")

    if setup_id.startswith("landry_classic_"):
        side = setup_side(setup_id)
        rows = compile_landry_classic_orders(
            df,
            setup_id,
            side,
            tick_size=tick_size,
            min_pullback_bars=landry_min_pullback_bars,
            max_pullback_bars=landry_max_pullback_bars,
            trend_lookback=landry_trend_lookback,
        )
        orders = pd.DataFrame(rows)
    else:
        orders = compile_setup_orders(
            df,
            setup_id,
            tick_size=tick_size,
            landry_valid_bars=landry_valid_bars,
            bowtie_transition_bars=bowtie_transition_bars,
        )

    exit_rules = build_exit_rules(exit_label, setup_id)
    exit_signal = compile_rules_signal(df, exit_rules) if exit_rules else None
    config = BacktestConfig(
        initial_capital=float(capital),
        position_size_pct=float(position_size_pct),
        commission_bps=float(commission_bps),
        slippage_bps=float(slippage_bps),
        take_profit_pct=None if setup_id.startswith("landry_classic_") else take_profit_pct,
        periods_per_year=PERIODS_PER_YEAR[timeframe],
    )

    if setup_id.startswith("landry_classic_"):
        result = run_landry_classic_backtest(
            df,
            orders=orders,
            exit_signal=exit_signal,
            config=config,
            same_bar_policy=same_bar_policy,
            partial_fraction=0.50,
            trailing_bars=landry_trailing_bars,
            tick_size=tick_size,
        )
    else:
        result = run_order_backtest(
            df,
            orders=orders,
            exit_signal=exit_signal,
            config=config,
            same_bar_policy=same_bar_policy,
        )
    return df, orders, result


def summary_row(ticker: str, result: BacktestResult, order_count: int) -> dict:
    m = result.metrics
    return {
        "Ticker": ticker,
        "Ordens": int(order_count),
        "Trades": int(m.get("trades", 0)),
        "Retorno %": float(m.get("total_return_pct", 0.0)),
        "CAGR %": float(m.get("cagr_pct", float("nan"))),
        "Drawdown máx. %": float(m.get("max_drawdown_pct", 0.0)),
        "Sharpe": float(m.get("sharpe", float("nan"))),
        "Sortino": float(m.get("sortino", float("nan"))),
        "Win rate %": float(m.get("win_rate_pct", float("nan"))),
        "Profit factor": float(m.get("profit_factor", float("nan"))),
        "Payoff": float(m.get("payoff", float("nan"))),
        "Expectância R$": float(m.get("expectancy", float("nan"))),
        "Equity final R$": float(m.get("final_equity", float("nan"))),
    }


def finite_or_none(value):
    try:
        value = float(value)
    except Exception:
        return None
    return value if math.isfinite(value) else None
