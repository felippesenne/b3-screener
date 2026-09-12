from __future__ import annotations

import math

import pandas as pd

from indicators import ema, rsi_wilder


STRUCTURE_SETUP_OPS = {
    "pivot_123_buy",
    "pivot_123_sell",
    "hns_buy",
    "hns_sell",
    "double_bottom",
    "double_top",
    "divergence_structure_buy",
    "divergence_structure_sell",
    "setup_91_structure_buy",
    "setup_91_structure_sell",
}


STRUCTURE_SETUP_DESCRIPTIONS = {
    "pivot_123_buy": (
        "Pivô 1-2-3 — Alta: P1 é um fundo, P2 um topo de reação e P3 um fundo mais alto; "
        "gatilho na superação de P2 e stop abaixo de P3. Exige perna P1→P2 de pelo menos 2%."
    ),
    "pivot_123_sell": (
        "Pivô 1-2-3 — Baixa: P1 é um topo, P2 um fundo de reação e P3 um topo mais baixo; "
        "gatilho na perda de P2 e stop acima de P3. Exige perna P1→P2 de pelo menos 2%."
    ),
    "hns_sell": (
        "OCO — Venda: ombro esquerdo, cabeça mais alta e ombro direito de altura semelhante ao esquerdo; "
        "pescoço aproximadamente horizontal. Gatilho na perda da linha de pescoço."
    ),
    "hns_buy": (
        "OCO Invertido — Compra: ombro esquerdo, cabeça mais baixa e ombro direito de profundidade semelhante; "
        "pescoço aproximadamente horizontal. Gatilho no rompimento da linha de pescoço."
    ),
    "double_bottom": (
        "Fundo Duplo — Compra: dois fundos em região semelhante (tolerância de 3%) separados por reação de pelo menos 2%; "
        "gatilho no rompimento do topo intermediário."
    ),
    "double_top": (
        "Topo Duplo — Venda: dois topos em região semelhante (tolerância de 3%) separados por correção de pelo menos 2%; "
        "gatilho na perda do fundo intermediário."
    ),
    "divergence_structure_buy": (
        "Divergência + Estrutura — Compra: preço faz segundo fundo igual ou mais baixo, IFR14 faz fundo mais alto "
        "por pelo menos 3 pontos e a entrada ocorre no rompimento do topo intermediário."
    ),
    "divergence_structure_sell": (
        "Divergência + Estrutura — Venda: preço faz segundo topo igual ou mais alto, IFR14 faz topo mais baixo "
        "por pelo menos 3 pontos e a entrada ocorre na perda do fundo intermediário."
    ),
    "setup_91_structure_buy": (
        "9.1 + Estrutura — Compra: existe estrutura 1-2-3 de alta e a MME9 vira para cima no P3 ou até 4 candles depois; "
        "gatilho na máxima do candle que virou a MME9, com stop estrutural em P3."
    ),
    "setup_91_structure_sell": (
        "9.1 + Estrutura — Venda: existe estrutura 1-2-3 de baixa e a MME9 vira para baixo no P3 ou até 4 candles depois; "
        "gatilho na mínima do candle que virou a MME9, com stop estrutural em P3."
    ),
}


def _finite(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except Exception:
        return False


def _state(
    *,
    passed: bool,
    name: str,
    status: str,
    direction: str | None = None,
    signal_date=None,
    trigger_date=None,
    entry: float | None = None,
    stop: float | None = None,
) -> dict:
    return {
        "passed": bool(passed),
        "name": name,
        "status": status,
        "direction": direction,
        "signal_date": signal_date,
        "trigger_date": trigger_date,
        "entry": entry,
        "stop": stop,
    }


def _is_swing_low(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["Low"].iloc[i])
    left = float(df["Low"].iloc[i - strength:i].astype(float).min())
    right = float(df["Low"].iloc[i + 1:i + strength + 1].astype(float).min())
    return bool(value <= left and value <= right and (value < left or value < right))


def _is_swing_high(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["High"].iloc[i])
    left = float(df["High"].iloc[i - strength:i].astype(float).max())
    right = float(df["High"].iloc[i + 1:i + strength + 1].astype(float).max())
    return bool(value >= left and value >= right and (value > left or value > right))


def _alternating_swings(df: pd.DataFrame, strength: int = 1, lookback: int = 220) -> list[dict]:
    if len(df) < 5:
        return []

    start = max(strength, len(df) - lookback)
    end = len(df) - strength
    raw: list[dict] = []
    for i in range(start, end):
        if _is_swing_low(df, i, strength):
            raw.append({"idx": i, "kind": "L", "value": float(df["Low"].iloc[i])})
        if _is_swing_high(df, i, strength):
            raw.append({"idx": i, "kind": "H", "value": float(df["High"].iloc[i])})

    raw.sort(key=lambda item: (item["idx"], item["kind"]))
    cleaned: list[dict] = []
    for event in raw:
        if cleaned and event["idx"] == cleaned[-1]["idx"]:
            # Um candle externo pode ser topo e fundo ao mesmo tempo. Mantemos o evento
            # que preserva a alternância da sequência anterior.
            if len(cleaned) >= 2 and event["kind"] != cleaned[-2]["kind"]:
                cleaned[-1] = event
            continue

        if not cleaned or event["kind"] != cleaned[-1]["kind"]:
            cleaned.append(event)
            continue

        current = cleaned[-1]
        more_extreme = (
            event["value"] < current["value"]
            if event["kind"] == "L"
            else event["value"] > current["value"]
        )
        if more_extreme:
            cleaned[-1] = event
    return cleaned


def _classify_candidate(
    df: pd.DataFrame,
    candidate: dict,
    *,
    side: str,
    name: str,
    confirmed_window: int = 10,
    armed_max_age: int = 40,
    stop_tolerance_pct: float = 0.001,
) -> tuple[int, int, dict] | None:
    signal_idx = int(candidate["signal_idx"])
    trigger_idx = int(candidate.get("trigger_idx", signal_idx))
    entry = float(candidate["entry"])
    stop = float(candidate["stop"])
    last = len(df) - 1
    breakout_idx: int | None = None

    for j in range(signal_idx + 1, len(df)):
        high = float(df["High"].iloc[j])
        low = float(df["Low"].iloc[j])
        if side == "buy":
            broke = high >= entry
            invalidated = low < stop * (1.0 - stop_tolerance_pct)
        else:
            broke = low <= entry
            invalidated = high > stop * (1.0 + stop_tolerance_pct)

        if breakout_idx is None:
            if invalidated:
                return None
            if broke:
                breakout_idx = j

    direction = "Compra" if side == "buy" else "Venda"
    summary = candidate.get("summary", "estrutura válida")
    signal_date = df.index[signal_idx]
    trigger_date = df.index[trigger_idx]
    close_now = float(df["Close"].iloc[-1])

    if breakout_idx is not None:
        age = last - breakout_idx
        if age > confirmed_window:
            return None
        structure_alive = (
            close_now >= stop * (1.0 - stop_tolerance_pct)
            if side == "buy"
            else close_now <= stop * (1.0 + stop_tolerance_pct)
        )
        if not structure_alive:
            return None
        age_text = "no último candle" if age == 0 else f"há {age} candle{'s' if age != 1 else ''}"
        return (
            breakout_idx,
            2,
            _state(
                passed=True,
                name=name,
                status=f"CONFIRMADO {age_text}; {summary}",
                direction=direction,
                signal_date=signal_date,
                trigger_date=trigger_date,
                entry=entry,
                stop=stop,
            ),
        )

    age = last - signal_idx
    if age > armed_max_age:
        return None
    return (
        signal_idx,
        1,
        _state(
            passed=True,
            name=name,
            status=f"ARMADO; {summary}",
            direction=direction,
            signal_date=signal_date,
            trigger_date=trigger_date,
            entry=entry,
            stop=stop,
        ),
    )


def _best_candidate_state(
    df: pd.DataFrame,
    candidates: list[dict],
    *,
    side: str,
    name: str,
    confirmed_window: int = 10,
    armed_max_age: int = 40,
) -> dict:
    direction = "Compra" if side == "buy" else "Venda"
    if not candidates:
        return _state(passed=False, name=name, status="nenhuma estrutura válida encontrada", direction=direction)

    classified = []
    for candidate in candidates:
        item = _classify_candidate(
            df,
            candidate,
            side=side,
            name=name,
            confirmed_window=confirmed_window,
            armed_max_age=armed_max_age,
        )
        if item is not None:
            classified.append(item)

    if not classified:
        return _state(
            passed=False,
            name=name,
            status=f"{len(candidates)} estrutura(s) encontradas, mas nenhuma permanece armada ou confirmada recentemente",
            direction=direction,
        )

    _, _, state = max(classified, key=lambda item: (item[0], item[1]))
    return state


def _pivot_123_candidates(df: pd.DataFrame, side: str) -> list[dict]:
    swings = _alternating_swings(df)
    candidates: list[dict] = []
    for first, second, third in zip(swings, swings[1:], swings[2:]):
        kinds = (first["kind"], second["kind"], third["kind"])
        if side == "buy" and kinds == ("L", "H", "L"):
            if third["value"] <= first["value"] * 1.002:
                continue
            leg_pct = (second["value"] / first["value"]) - 1.0
            if leg_pct < 0.02:
                continue
            candidates.append({
                "signal_idx": third["idx"],
                "trigger_idx": second["idx"],
                "entry": second["value"],
                "stop": third["value"],
                "p1_idx": first["idx"],
                "p2_idx": second["idx"],
                "p3_idx": third["idx"],
                "summary": (
                    f"P1/fundo {first['value']:.2f} · P2/gatilho {second['value']:.2f} · "
                    f"P3/stop {third['value']:.2f}"
                ),
            })
        elif side == "sell" and kinds == ("H", "L", "H"):
            if third["value"] >= first["value"] * 0.998:
                continue
            leg_pct = 1.0 - (second["value"] / first["value"])
            if leg_pct < 0.02:
                continue
            candidates.append({
                "signal_idx": third["idx"],
                "trigger_idx": second["idx"],
                "entry": second["value"],
                "stop": third["value"],
                "p1_idx": first["idx"],
                "p2_idx": second["idx"],
                "p3_idx": third["idx"],
                "summary": (
                    f"P1/topo {first['value']:.2f} · P2/gatilho {second['value']:.2f} · "
                    f"P3/stop {third['value']:.2f}"
                ),
            })
    return candidates


def _pivot_123_state(df: pd.DataFrame, side: str) -> dict:
    name = "Pivô 1-2-3 — Alta" if side == "buy" else "Pivô 1-2-3 — Baixa"
    return _best_candidate_state(df, _pivot_123_candidates(df, side), side=side, name=name)


def _double_candidates(df: pd.DataFrame, side: str) -> list[dict]:
    swings = _alternating_swings(df)
    candidates: list[dict] = []
    for first, middle, second in zip(swings, swings[1:], swings[2:]):
        kinds = (first["kind"], middle["kind"], second["kind"])
        if side == "buy" and kinds == ("L", "H", "L"):
            avg_bottom = (first["value"] + second["value"]) / 2.0
            if avg_bottom <= 0:
                continue
            similarity = abs(first["value"] - second["value"]) / avg_bottom
            reaction = (middle["value"] / avg_bottom) - 1.0
            if similarity > 0.03 or reaction < 0.02:
                continue
            candidates.append({
                "signal_idx": second["idx"],
                "trigger_idx": middle["idx"],
                "entry": middle["value"],
                "stop": min(first["value"], second["value"]),
                "summary": (
                    f"fundos {first['value']:.2f}/{second['value']:.2f} · neckline/gatilho {middle['value']:.2f} · "
                    f"diferença {similarity * 100:.1f}%"
                ),
            })
        elif side == "sell" and kinds == ("H", "L", "H"):
            avg_top = (first["value"] + second["value"]) / 2.0
            if avg_top <= 0:
                continue
            similarity = abs(first["value"] - second["value"]) / avg_top
            reaction = 1.0 - (middle["value"] / avg_top)
            if similarity > 0.03 or reaction < 0.02:
                continue
            candidates.append({
                "signal_idx": second["idx"],
                "trigger_idx": middle["idx"],
                "entry": middle["value"],
                "stop": max(first["value"], second["value"]),
                "summary": (
                    f"topos {first['value']:.2f}/{second['value']:.2f} · neckline/gatilho {middle['value']:.2f} · "
                    f"diferença {similarity * 100:.1f}%"
                ),
            })
    return candidates


def _double_state(df: pd.DataFrame, side: str) -> dict:
    name = "Fundo Duplo" if side == "buy" else "Topo Duplo"
    return _best_candidate_state(df, _double_candidates(df, side), side=side, name=name)


def _hns_candidates(df: pd.DataFrame, side: str) -> list[dict]:
    swings = _alternating_swings(df)
    candidates: list[dict] = []
    for a, b, c, d, e in zip(swings, swings[1:], swings[2:], swings[3:], swings[4:]):
        kinds = (a["kind"], b["kind"], c["kind"], d["kind"], e["kind"])

        if side == "sell" and kinds == ("H", "L", "H", "L", "H"):
            shoulders_avg = (a["value"] + e["value"]) / 2.0
            neck_avg = (b["value"] + d["value"]) / 2.0
            if shoulders_avg <= 0 or neck_avg <= 0:
                continue
            shoulder_similarity = abs(a["value"] - e["value"]) / shoulders_avg
            neckline_similarity = abs(b["value"] - d["value"]) / neck_avg
            head_prominence = c["value"] / max(a["value"], e["value"]) - 1.0
            pattern_height = c["value"] / neck_avg - 1.0
            if shoulder_similarity > 0.05 or neckline_similarity > 0.06:
                continue
            if head_prominence < 0.015 or pattern_height < 0.04:
                continue
            entry = min(b["value"], d["value"])
            candidates.append({
                "signal_idx": e["idx"],
                "trigger_idx": d["idx"],
                "entry": entry,
                "stop": e["value"],
                "summary": (
                    f"ombro E {a['value']:.2f} · cabeça {c['value']:.2f} · ombro D {e['value']:.2f} · "
                    f"neckline/gatilho {entry:.2f}"
                ),
            })

        elif side == "buy" and kinds == ("L", "H", "L", "H", "L"):
            shoulders_avg = (a["value"] + e["value"]) / 2.0
            neck_avg = (b["value"] + d["value"]) / 2.0
            if shoulders_avg <= 0 or neck_avg <= 0:
                continue
            shoulder_similarity = abs(a["value"] - e["value"]) / shoulders_avg
            neckline_similarity = abs(b["value"] - d["value"]) / neck_avg
            head_prominence = min(a["value"], e["value"]) / c["value"] - 1.0
            pattern_height = neck_avg / c["value"] - 1.0
            if shoulder_similarity > 0.05 or neckline_similarity > 0.06:
                continue
            if head_prominence < 0.015 or pattern_height < 0.04:
                continue
            entry = max(b["value"], d["value"])
            candidates.append({
                "signal_idx": e["idx"],
                "trigger_idx": d["idx"],
                "entry": entry,
                "stop": e["value"],
                "summary": (
                    f"ombro E {a['value']:.2f} · cabeça {c['value']:.2f} · ombro D {e['value']:.2f} · "
                    f"neckline/gatilho {entry:.2f}"
                ),
            })
    return candidates


def _hns_state(df: pd.DataFrame, side: str) -> dict:
    name = "OCO Invertido" if side == "buy" else "OCO"
    return _best_candidate_state(df, _hns_candidates(df, side), side=side, name=name, armed_max_age=50)


def _divergence_candidates(df: pd.DataFrame, side: str) -> list[dict]:
    swings = _alternating_swings(df)
    rsi14 = rsi_wilder(df["Close"].astype(float), 14)
    candidates: list[dict] = []

    for first, middle, second in zip(swings, swings[1:], swings[2:]):
        kinds = (first["kind"], middle["kind"], second["kind"])
        rsi_first = rsi14.iloc[first["idx"]]
        rsi_second = rsi14.iloc[second["idx"]]
        if not (_finite(rsi_first) and _finite(rsi_second)):
            continue
        r1, r2 = float(rsi_first), float(rsi_second)

        if side == "buy" and kinds == ("L", "H", "L"):
            # Divergência altista regular: preço faz fundo igual/mais baixo e IFR faz fundo mais alto.
            if second["value"] > first["value"] * 1.003 or r2 < r1 + 3.0:
                continue
            candidates.append({
                "signal_idx": second["idx"],
                "trigger_idx": middle["idx"],
                "entry": middle["value"],
                "stop": min(first["value"], second["value"]),
                "summary": (
                    f"preço {first['value']:.2f}→{second['value']:.2f} · IFR14 {r1:.1f}→{r2:.1f} · "
                    f"gatilho estrutural {middle['value']:.2f}"
                ),
            })

        elif side == "sell" and kinds == ("H", "L", "H"):
            # Divergência baixista regular: preço faz topo igual/mais alto e IFR faz topo mais baixo.
            if second["value"] < first["value"] * 0.997 or r2 > r1 - 3.0:
                continue
            candidates.append({
                "signal_idx": second["idx"],
                "trigger_idx": middle["idx"],
                "entry": middle["value"],
                "stop": max(first["value"], second["value"]),
                "summary": (
                    f"preço {first['value']:.2f}→{second['value']:.2f} · IFR14 {r1:.1f}→{r2:.1f} · "
                    f"gatilho estrutural {middle['value']:.2f}"
                ),
            })
    return candidates


def _divergence_state(df: pd.DataFrame, side: str) -> dict:
    name = "Divergência + Estrutura — Compra" if side == "buy" else "Divergência + Estrutura — Venda"
    return _best_candidate_state(df, _divergence_candidates(df, side), side=side, name=name, armed_max_age=35)


def _ema9_turns(df: pd.DataFrame, side: str) -> list[int]:
    e9 = ema(df["Close"].astype(float), 9)
    turns: list[int] = []
    for i in range(2, len(df)):
        a, b, c = e9.iloc[i - 2], e9.iloc[i - 1], e9.iloc[i]
        if not (_finite(a) and _finite(b) and _finite(c)):
            continue
        if side == "buy" and b < a and c > b:
            turns.append(i)
        elif side == "sell" and b > a and c < b:
            turns.append(i)
    return turns


def _setup_91_structure_candidates(df: pd.DataFrame, side: str) -> list[dict]:
    structures = _pivot_123_candidates(df, side)
    turns = _ema9_turns(df, side)
    candidates: list[dict] = []

    for structure in structures:
        p3_idx = int(structure["p3_idx"])
        valid_turns = [i for i in turns if p3_idx <= i <= p3_idx + 4]
        if not valid_turns:
            continue
        turn_idx = valid_turns[0]
        stop = float(structure["stop"])

        if side == "buy":
            if float(df["Low"].iloc[p3_idx:turn_idx + 1].min()) < stop * 0.999:
                continue
            entry = float(df["High"].iloc[turn_idx])
        else:
            if float(df["High"].iloc[p3_idx:turn_idx + 1].max()) > stop * 1.001:
                continue
            entry = float(df["Low"].iloc[turn_idx])

        candidates.append({
            "signal_idx": turn_idx,
            "trigger_idx": turn_idx,
            "entry": entry,
            "stop": stop,
            "summary": (
                f"estrutura P1-P2-P3 confirmada · P2 {structure['entry']:.2f} · P3/stop {stop:.2f} · "
                f"candle 9.1/gatilho {entry:.2f}"
            ),
        })
    return candidates


def _setup_91_structure_state(df: pd.DataFrame, side: str) -> dict:
    name = "9.1 + Estrutura — Compra" if side == "buy" else "9.1 + Estrutura — Venda"
    return _best_candidate_state(
        df,
        _setup_91_structure_candidates(df, side),
        side=side,
        name=name,
        confirmed_window=5,
        armed_max_age=12,
    )


def structure_setup_state(df: pd.DataFrame, op: str) -> dict:
    if op == "pivot_123_buy":
        return _pivot_123_state(df, "buy")
    if op == "pivot_123_sell":
        return _pivot_123_state(df, "sell")
    if op == "hns_buy":
        return _hns_state(df, "buy")
    if op == "hns_sell":
        return _hns_state(df, "sell")
    if op == "double_bottom":
        return _double_state(df, "buy")
    if op == "double_top":
        return _double_state(df, "sell")
    if op == "divergence_structure_buy":
        return _divergence_state(df, "buy")
    if op == "divergence_structure_sell":
        return _divergence_state(df, "sell")
    if op == "setup_91_structure_buy":
        return _setup_91_structure_state(df, "buy")
    if op == "setup_91_structure_sell":
        return _setup_91_structure_state(df, "sell")
    raise ValueError(f"Setup estrutural não suportado: {op}")


def structure_setup_description(op: str) -> str:
    return STRUCTURE_SETUP_DESCRIPTIONS.get(op, op)
