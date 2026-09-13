from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if b not in (0, 0.0) else float("nan")


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_capital: float,
    periods_per_year: int = 252,
) -> dict:
    """Compute a compact set of performance statistics.

    Expected equity_curve columns: Equity. The index should be chronological.
    Trades may be empty; when present, PnL and ReturnPct are used.
    """
    if equity_curve is None or equity_curve.empty:
        return {
            "initial_capital": float(initial_capital),
            "final_equity": float(initial_capital),
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": float("nan"),
            "sortino": float("nan"),
            "trades": 0,
            "win_rate_pct": float("nan"),
            "profit_factor": float("nan"),
            "payoff": float("nan"),
            "expectancy": float("nan"),
        }

    equity = equity_curve["Equity"].astype(float)
    final_equity = float(equity.iloc[-1])
    total_return = final_equity / float(initial_capital) - 1.0

    n_periods = max(len(equity) - 1, 1)
    years = n_periods / float(periods_per_year)
    cagr = (final_equity / float(initial_capital)) ** (1.0 / years) - 1.0 if years > 0 and final_equity > 0 else float("nan")

    rolling_max = equity.cummax()
    drawdown = equity / rolling_max - 1.0
    max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0

    returns = equity.pct_change().dropna()
    if len(returns) >= 2 and float(returns.std(ddof=1)) > 0:
        sharpe = math.sqrt(periods_per_year) * float(returns.mean()) / float(returns.std(ddof=1))
    else:
        sharpe = float("nan")

    downside = returns[returns < 0]
    if len(downside) >= 2 and float(downside.std(ddof=1)) > 0:
        sortino = math.sqrt(periods_per_year) * float(returns.mean()) / float(downside.std(ddof=1))
    else:
        sortino = float("nan")

    if trades is None or trades.empty:
        trade_count = 0
        win_rate = profit_factor = payoff = expectancy = float("nan")
    else:
        pnl = trades["PnL"].astype(float)
        winners = pnl[pnl > 0]
        losers = pnl[pnl < 0]
        trade_count = int(len(pnl))
        win_rate = float((pnl > 0).mean())
        gross_profit = float(winners.sum()) if len(winners) else 0.0
        gross_loss = abs(float(losers.sum())) if len(losers) else 0.0
        profit_factor = _safe_div(gross_profit, gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else float("nan"))
        avg_win = float(winners.mean()) if len(winners) else float("nan")
        avg_loss = abs(float(losers.mean())) if len(losers) else float("nan")
        payoff = _safe_div(avg_win, avg_loss) if not np.isnan(avg_win) and not np.isnan(avg_loss) else float("nan")
        expectancy = float(pnl.mean())

    return {
        "initial_capital": float(initial_capital),
        "final_equity": final_equity,
        "total_return_pct": total_return * 100.0,
        "cagr_pct": cagr * 100.0 if not np.isnan(cagr) else float("nan"),
        "max_drawdown_pct": max_drawdown * 100.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "trades": trade_count,
        "win_rate_pct": win_rate * 100.0 if not np.isnan(win_rate) else float("nan"),
        "profit_factor": profit_factor,
        "payoff": payoff,
        "expectancy": expectancy,
    }
