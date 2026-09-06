from __future__ import annotations

import math
import operator

import pandas as pd

from classic_setups import (
    SPECIAL_SETUP_OPS,
    evaluate_context_filters,
    special_setup_description,
    special_setup_state,
)
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
        name = "Setup 9.1 Compra"
    else:
        entry = trigger_low
        stop = trigger_high
        breaks = [
            j for j in range(trigger_idx + 1, len(df))
            if _finite(df["Low"].iloc[j]) and float(df["Low"].iloc[j]) < trigger_low
        ]
        direction = "Venda"
        name = "Setup 9.1 Venda"

    first_break = breaks[0] if breaks else None

    validation_end = first_break if first_break is not None else len(ema9)
    for j in range(trigger_idx + 1, validation_end):
        if not (_finite(ema9.iloc[j - 1]) and _finite(ema9.iloc[j])):
            return {"passed": False, "status": "sem dados suficientes", "name": name}
        if side == "buy" and ema9.iloc[j] <= ema9.iloc[j - 1]:
            return {
                "passed": False,
                "status": "MME9 deixou de apontar para cima antes da entrada",
                "name": name,
                "direction": direction,
                "trigger_date": trigger_date,
                "signal_date": trigger_date,
                "entry": entry,
                "stop": stop,
            }
        if side == "sell" and ema9.iloc[j] >= ema9.iloc[j - 1]:
            return {
                "passed": False,
                "status": "MME9 deixou de apontar para baixo antes da entrada",
                "name": name,
                "direction": direction,
                "trigger_date": trigger_date,
                "signal_date": trigger_date,
                "entry": entry,
                "stop": stop,
            }

    if trigger_idx == len(df) - 1:
        status = "Candle-gatilho formado"
        passed = True
    elif first_break is None:
        status = "Aguardando rompimento"
        passed = True
    elif first_break == len(df) - 1:
        status = "Entrada acionada no último candle"
        passed = True
    else:
        status = "Entrada já acionada anteriormente"
        passed = False

    return {
        "passed": passed,
        "name": name,
        "status": status,
        "direction": direction,
        "trigger_idx": trigger_idx,
        "trigger_date": trigger_date,
        "signal_date": trigger_date,
        "entry": entry,
        "stop": stop,
        "trigger_high": trigger_high,
        "trigger_low": trigger_low,
    }


def _special_state(df: pd.DataFrame, cache: dict, rule: dict) -> dict | None:
    op = rule.get("operator")
    left = _series_for(cache, rule["left"])
    if op in {"setup_91_buy", "setup_91_sell"}:
        side = "buy" if op == "setup_91_buy" else "sell"
        return _setup_91_state(df, left, side)
    if op in SPECIAL_SETUP_OPS:
        return special_setup_state(df, op, left)
    return None


def evaluate_rule(df: pd.DataFrame, cache: dict, rule: dict) -> tuple[bool, str]:
    left = _series_for(cache, rule["left"])
    op = rule["operator"]
    left_now = left.iloc[-1]

    if not _finite(left_now):
        return False, "sem dados suficientes"

    state = _special_state(df, cache, rule)
    if state is not None:
        name = state.get("name", "Setup especial")
        status = state.get("status", "estado indisponível")
        return bool(state.get("passed", False)), f"{name}: {status}"

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
    op_labels = {
        "<": "<",
        "<=": "<=",
        ">": ">",
        ">=": ">=",
        "==": "=",
        "crosses_above": "cruza acima de",
        "crosses_below": "cruza abaixo de",
        "rising": "ascendente",
        "falling": "descendente",
    }

    for i, rule in enumerate(rules):
        op = rule.get("operator", "")

        if op == "setup_91_buy":
            expr = "Setup 9.1 clássico — Compra: MME9 vinha caindo e virou para cima; entrada no rompimento da máxima do candle-gatilho"
        elif op == "setup_91_sell":
            expr = "Setup 9.1 clássico — Venda: MME9 vinha subindo e virou para baixo; entrada no rompimento da mínima do candle-gatilho"
        elif op in SPECIAL_SETUP_OPS:
            expr = special_setup_description(op)
        else:
            left = indicator_label(rule["left"])
            op_text = op_labels.get(op, op or "operador desconhecido")
            if op in {"rising", "falling"}:
                expr = f"{left} {op_text}"
            elif rule.get("right_kind") == "value":
                expr = f"{left} {op_text} {float(rule.get('right_value', 0)):g}"
            elif rule.get("right_kind") == "price":
                expr = f"{left} {op_text} Fechamento"
            elif rule.get("right_kind") == "indicator" and rule.get("right"):
                expr = f"{left} {op_text} {indicator_label(rule['right'])}"
            else:
                expr = f"{left} {op_text}".strip()

        if i > 0:
            expr = f"{rule.get('connector', 'AND')} {expr}"
        parts.append(expr)

    return " ".join(parts)


def evaluate_latest(
    ticker: str,
    df: pd.DataFrame,
    rules: list[dict],
    context_filters: list[str] | None = None,
) -> dict:
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

        state = _special_state(df, cache, rule)
        if state is not None:
            setup_state = state

    strategy_passed = combine_results(checks, connectors)
    context_passed, context_details = evaluate_context_filters(df, context_filters)
    passed = bool(strategy_passed and context_passed)

    row = {
        "Ticker": ticker,
        "Fechamento": round(float(df["Close"].iloc[-1]), 2),
        "Data": df.index[-1].strftime("%d/%m/%Y"),
        "Passou": passed,
        "Estratégia OK": bool(strategy_passed),
        "Contexto OK": bool(context_passed),
        "Regras aprovadas": f"{sum(checks)}/{len(checks)}",
        "Detalhes": " | ".join(rule_details),
        "Filtros de contexto": " | ".join(context_details) if context_details else "Nenhum",
    }

    if setup_state:
        row["Setup"] = setup_state.get("name", "Setup especial")
        row["Status setup"] = setup_state.get("status", "")
        signal_date = setup_state.get("signal_date")
        trigger_date = setup_state.get("trigger_date")
        if signal_date is not None:
            row["Candle-sinal"] = signal_date.strftime("%d/%m/%Y")
        if trigger_date is not None and trigger_date is not signal_date:
            row["Candle-gatilho"] = trigger_date.strftime("%d/%m/%Y")
        if setup_state.get("entry") is not None:
            row["Entrada / gatilho"] = round(float(setup_state["entry"]), 2)
        if setup_state.get("stop") is not None:
            row["Stop"] = round(float(setup_state["stop"]), 2)

    for rule in rules:
        label = indicator_label(rule["left"])
        value = _series_for(cache, rule["left"]).iloc[-1]
        if label not in row and _finite(value):
            row[label] = round(float(value), 4)
    return row


def scan_universe(
    tickers,
    provider,
    timeframe,
    period,
    rules,
    context_filters: list[str] | None = None,
):
    rows = []
    errors = {}
    histories = None

    if len(tickers) > 1 and hasattr(provider, "get_histories"):
        try:
            histories, batch_errors = provider.get_histories(list(tickers), period=period)
            errors.update(batch_errors)
        except Exception:
            histories = None
            errors = {}

    for ticker in tickers:
        try:
            if histories is None:
                raw = provider.get_history(ticker, period=period)
            else:
                raw = histories.get(ticker)
                if raw is None or raw.empty:
                    if ticker in errors:
                        continue
                    raise ValueError("Sem histórico disponível.")

            tf = resample_ohlcv(raw, timeframe)
            if len(tf) < 3:
                raise ValueError("Histórico insuficiente para cálculo.")
            rows.append(evaluate_latest(ticker, tf, rules, context_filters=context_filters))
            errors.pop(ticker, None)
        except Exception as exc:
            errors[ticker] = str(exc)

    if not rows:
        return pd.DataFrame(), errors

    result = pd.DataFrame(rows)
    result = result.sort_values(by=["Passou", "Ticker"], ascending=[False, True]).reset_index(drop=True)
    return result, errors
