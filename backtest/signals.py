from __future__ import annotations

import operator

import pandas as pd

from classic_setups import SPECIAL_SETUP_OPS
from indicators import build_series_cache, spec_key
from .engine import BacktestConfig, BacktestResult, run_backtest

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}
UNSUPPORTED_TRIGGER_OPS = set(SPECIAL_SETUP_OPS) | {"setup_91_buy", "setup_91_sell"}


def _right_series(df: pd.DataFrame, cache: dict, rule: dict) -> pd.Series:
    kind = rule.get("right_kind")
    if kind == "value":
        return pd.Series(float(rule["right_value"]), index=df.index, dtype=float)
    if kind == "price":
        return df["Close"].astype(float)
    if kind == "indicator":
        return cache[spec_key(rule["right"])].astype(float)
    raise ValueError(f"right_kind não suportado: {kind}")


def compile_rules_signal(df: pd.DataFrame, rules: list[dict]) -> pd.Series:
    """Compile ordinary Strategy Builder rules into a historical boolean series.

    This compiler intentionally rejects setups that depend on stop/trigger orders.
    Those require an order-aware adapter so the backtest does not silently change
    the original setup semantics.
    """
    if not rules:
        return pd.Series(False, index=df.index, dtype=bool)

    unsupported = [rule.get("operator") for rule in rules if rule.get("operator") in UNSUPPORTED_TRIGGER_OPS]
    if unsupported:
        names = ", ".join(sorted(set(unsupported)))
        raise NotImplementedError(
            f"Setup(s) com gatilho ainda exigem adaptador de ordens específico: {names}"
        )

    specs: list[dict] = []
    for rule in rules:
        specs.append(rule["left"])
        if rule.get("right_kind") == "indicator":
            specs.append(rule["right"])
    cache = build_series_cache(df, specs)

    rule_series: list[pd.Series] = []
    connectors: list[str] = []

    for idx, rule in enumerate(rules):
        left = cache[spec_key(rule["left"])].astype(float)
        op = rule["operator"]

        if op == "rising":
            current = left > left.shift(1)
        elif op == "falling":
            current = left < left.shift(1)
        else:
            right = _right_series(df, cache, rule)
            if op in OPS:
                current = OPS[op](left, right)
            elif op == "crosses_above":
                current = (left.shift(1) <= right.shift(1)) & (left > right)
            elif op == "crosses_below":
                current = (left.shift(1) >= right.shift(1)) & (left < right)
            else:
                raise ValueError(f"Operador não suportado no backtest: {op}")

        rule_series.append(current.fillna(False).astype(bool))
        if idx > 0:
            connectors.append(rule.get("connector", "AND"))

    combined = rule_series[0].copy()
    for idx, connector in enumerate(connectors, start=1):
        if connector == "AND":
            combined = combined & rule_series[idx]
        elif connector == "OR":
            combined = combined | rule_series[idx]
        else:
            raise ValueError(f"Conector não suportado: {connector}")

    return combined.fillna(False).astype(bool)


def run_rules_backtest(
    df: pd.DataFrame,
    entry_rules: list[dict],
    exit_rules: list[dict] | None = None,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    entry_signal = compile_rules_signal(df, entry_rules)
    exit_signal = compile_rules_signal(df, exit_rules) if exit_rules else None
    return run_backtest(df, entry_signal=entry_signal, exit_signal=exit_signal, config=config)
