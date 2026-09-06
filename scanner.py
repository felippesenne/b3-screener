import math
import operator
import pandas as pd

from indicators import build_series_cache, indicator_label, resample_ohlcv, spec_key

OPS = {"<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq}


def _series_for(cache: dict, spec: dict) -> pd.Series:
    return cache[spec_key(spec)]


def _right_series(df: pd.DataFrame, cache: dict, rule: dict):
    if rule.get("right_kind") == "indicator":
        return _series_for(cache, rule["right"])
    if rule.get("right_kind") == "price":
        return df["Close"].astype(float)
    return None


def _finite(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except Exception:
        return False


def evaluate_rule(df: pd.DataFrame, cache: dict, rule: dict) -> tuple[bool, str]:
    left = _series_for(cache, rule["left"])
    op = rule["operator"]
    left_now = left.iloc[-1]

    if not _finite(left_now):
        return False, "sem dados suficientes"

    if op in {"rising", "falling"}:
        if len(left) < 2 or not _finite(left.iloc[-2]):
            return False, "sem dados suficientes"
        passed = left_now > left.iloc[-2] if op == "rising" else left_now < left.iloc[-2]
        desc = "ascendente" if op == "rising" else "descendente"
        return bool(passed), f"{indicator_label(rule['left'])} {desc}"

    if rule.get("right_kind") == "value":
        right_now = float(rule["right_value"])
        right_prev = right_now
        right_label = f"{right_now:g}"
    else:
        right = _right_series(df, cache, rule)
        if right is None or not _finite(right.iloc[-1]):
            return False, "sem dados suficientes"
        right_now = right.iloc[-1]
        right_prev = right.iloc[-2] if len(right) >= 2 else float("nan")
        right_label = "Fechamento" if rule.get("right_kind") == "price" else indicator_label(rule["right"])

    if op in OPS:
        passed = OPS[op](float(left_now), float(right_now))
        return bool(passed), f"{indicator_label(rule['left'])} {op} {right_label}"

    if op in {"crosses_above", "crosses_below"}:
        if len(left) < 2 or not _finite(left.iloc[-2]) or not _finite(right_prev):
            return False, "sem dados suficientes"
        if op == "crosses_above":
            passed = left.iloc[-2] <= right_prev and left_now > right_now
            text = "cruzou acima de"
        else:
            passed = left.iloc[-2] >= right_prev and left_now < right_now
            text = "cruzou abaixo de"
        return bool(passed), f"{indicator_label(rule['left'])} {text} {right_label}"

    raise ValueError(f"Operador não suportado: {op}")


def combine_results(values: list[bool], connectors: list[str]) -> bool:
    if not values:
        return True
    result = bool(values[0])
    for idx, connector in enumerate(connectors, start=1):
        if idx >= len(values):
            break
        result = (result and values[idx]) if connector == "AND" else (result or values[idx])
    return bool(result)


def describe_strategy(rules: list[dict]) -> str:
    parts = []
    for i, rule in enumerate(rules):
        left = indicator_label(rule["left"])
        op = rule["operator"]
        op_text = {
            "<": "<", "<=": "<=", ">": ">", ">=": ">=", "==": "=",
            "crosses_above": "cruza acima de", "crosses_below": "cruza abaixo de",
            "rising": "ascendente", "falling": "descendente",
        }[op]
        if op in {"rising", "falling"}:
            expr = f"{left} {op_text}"
        elif rule.get("right_kind") == "value":
            expr = f"{left} {op_text} {rule['right_value']:g}"
        elif rule.get("right_kind") == "price":
            expr = f"{left} {op_text} Fechamento"
        else:
            expr = f"{left} {op_text} {indicator_label(rule['right'])}"
        if i > 0:
            expr = f"{rule.get('connector', 'AND')} {expr}"
        parts.append(expr)
    return " ".join(parts)


def evaluate_latest(ticker: str, df: pd.DataFrame, rules: list[dict]) -> dict:
    specs = []
    for rule in rules:
        specs.append(rule["left"])
        if rule.get("right_kind") == "indicator":
            specs.append(rule["right"])
    cache = build_series_cache(df, specs)

    checks = []
    rule_details = []
    connectors = []
    for idx, rule in enumerate(rules):
        passed, label = evaluate_rule(df, cache, rule)
        checks.append(passed)
        rule_details.append(f"{'✓' if passed else '✗'} {label}")
        if idx > 0:
            connectors.append(rule.get("connector", "AND"))

    passed = combine_results(checks, connectors)
    row = {
        "Ticker": ticker,
        "Fechamento": round(float(df["Close"].iloc[-1]), 2),
        "Data": df.index[-1].strftime("%d/%m/%Y"),
        "Passou": passed,
        "Regras aprovadas": f"{sum(checks)}/{len(checks)}",
        "Detalhes": " | ".join(rule_details),
    }

    for rule in rules:
        label = indicator_label(rule["left"])
        value = _series_for(cache, rule["left"]).iloc[-1]
        if label not in row and _finite(value):
            row[label] = round(float(value), 4)
    return row


def scan_universe(tickers, provider, timeframe, period, rules):
    rows = []
    errors = {}
    for ticker in tickers:
        try:
            raw = provider.get_history(ticker, period=period)
            tf = resample_ohlcv(raw, timeframe)
            if len(tf) < 3:
                raise ValueError("Histórico insuficiente para cálculo.")
            rows.append(evaluate_latest(ticker, tf, rules))
        except Exception as exc:
            errors[ticker] = str(exc)

    if not rows:
        return pd.DataFrame(), errors

    result = pd.DataFrame(rows)
    result = result.sort_values(by=["Passou", "Ticker"], ascending=[False, True]).reset_index(drop=True)
    return result, errors
