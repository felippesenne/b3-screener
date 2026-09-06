from __future__ import annotations

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


def _setup_91_state(df: pd.DataFrame, ema9: pd.Series, side: str) -> dict:
    """
    Detecta o Setup 9.1 clássico.

    Compra:
    - MME9 vinha caindo;
    - vira para cima em candle fechado (candle-gatilho);
    - enquanto a MME9 continuar subindo, o gatilho permanece válido;
    - entrada no rompimento da máxima do candle-gatilho;
    - stop na mínima do candle-gatilho.

    Venda é a lógica espelhada.
    """
    if len(df) < 3 or len(ema9) < 3:
        return {"passed": False, "status": "sem dados suficientes"}

    turns = []
    for i in range(2, len(ema9)):
        a, b, c = ema9.iloc[i - 2], ema9.iloc[i - 1], ema9.iloc[i]
        if not (_finite(a) and _finite(b) and _finite(c)):
            continue
        if side == "buy":
            turned = b < a and c > b
        else:
            turned = b > a and c < b
        if turned:
            turns.append(i)

    if not turns:
        return {"passed": False, "status": "nenhuma virada válida da MME9"}

    trigger_idx = turns[-1]

    # O setup perde validade se a MME9 deixar de apontar na direção do sinal
    # antes da entrada.
    for j in range(trigger_idx + 1, len(ema9)):
        if not (_finite(ema9.iloc[j - 1]) and _finite(ema9.iloc[j])):
            return {"passed": False, "status": "sem dados suficientes"}
        if side == "buy" and ema9.iloc[j] <= ema9.iloc[j - 1]:
            return {"passed": False, "status": "MME9 deixou de apontar para cima"}
        if side == "sell" and ema9.iloc[j] >= ema9.iloc[j - 1]:
            return {"passed": False, "status": "MME9 deixou de apontar para baixo"}

    trigger_high = float(df["High"].iloc[trigger_idx])
    trigger_low = float(df["Low"].iloc[trigger_idx])
    trigger_date = df.index[trigger_idx]

    if side == "buy":
        entry = trigger_high
        stop = trigger_low
        breaks = [
            j for j in range(trigger_idx + 1, len(df))
            if _finite(df["High"].iloc[j]) and float(df["High"].iloc[j]) > trigger_high
        ]
        direction = "Compra"
    else:
        entry = trigger_low
        stop = trigger_high
        breaks = [
            j for j in range(trigger_idx + 1, len(df))
            if _finite(df["Low"].iloc[j]) and float(df["Low"].iloc[j]) < trigger_low
        ]
        direction = "Venda"

    if trigger_idx == len(df) - 1:
        status = "Candle-gatilho formado"
        passed = True
    elif not breaks:
        status = "Aguardando rompimento"
        passed = True
    elif breaks[0] == len(df) - 1:
        status = "Entrada acionada no último candle"
        passed = True
    else:
        status = "Entrada já acionada anteriormente"
        passed = False

    return {
        "passed": passed,
        "status": status,
        "direction": direction,
        "trigger_idx": trigger_idx,
        "trigger_date": trigger_date,
        "entry": entry,
        "stop": stop,
        "trigger_high": trigger_high,
        "trigger_low": trigger_low,
    }


def evaluate_rule(df: pd.DataFrame, cache: dict, rule: dict) -> tuple[bool, str]:
    left = _series_for(cache, rule["left"])
    op = rule["operator"]
    left_now = left.iloc[-1]

    if not _finite(left_now):
        return False, "sem dados suficientes"

    if op in {"setup_91_buy", "setup_91_sell"}:
        side = "buy" if op == "setup_91_buy" else "sell"
        state = _setup_91_state(df, left, side)
        label = f"Setup 9.1 {state.get('direction', 'Compra' if side == 'buy' else 'Venda')}: {state['status']}"
        return bool(state["passed"]), label

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

        if op == "setup_91_buy":
            expr = "Setup 9.1 clássico — Compra: MME9 vinha caindo e virou para cima; entrada no rompimento da máxima do candle-gatilho"
        elif op == "setup_91_sell":
            expr = "Setup 9.1 clássico — Venda: MME9 vinha subindo e virou para baixo; entrada no rompimento da mínima do candle-gatilho"
        else:
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
    setup_state = None

    for idx, rule in enumerate(rules):
        passed, label = evaluate_rule(df, cache, rule)
        checks.append(passed)
        rule_details.append(f"{'✓' if passed else '✗'} {label}")
        if idx > 0:
            connectors.append(rule.get("connector", "AND"))

        if rule["operator"] in {"setup_91_buy", "setup_91_sell"}:
            side = "buy" if rule["operator"] == "setup_91_buy" else "sell"
            setup_state = _setup_91_state(df, _series_for(cache, rule["left"]), side)

    passed = combine_results(checks, connectors)
    row = {
        "Ticker": ticker,
        "Fechamento": round(float(df["Close"].iloc[-1]), 2),
        "Data": df.index[-1].strftime("%d/%m/%Y"),
        "Passou": passed,
        "Regras aprovadas": f"{sum(checks)}/{len(checks)}",
        "Detalhes": " | ".join(rule_details),
    }

    if setup_state and "entry" in setup_state:
        row["Status 9.1"] = setup_state["status"]
        row["Candle-gatilho"] = setup_state["trigger_date"].strftime("%d/%m/%Y")
        row["Entrada / gatilho"] = round(float(setup_state["entry"]), 2)
        row["Stop"] = round(float(setup_state["stop"]), 2)

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
