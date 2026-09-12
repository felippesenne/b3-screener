from __future__ import annotations

import math

import pandas as pd

from indicators import ema


TRADE_DE_VALOR_SETUP_OPS = {
    "landry_buy",
    "landry_sell",
    "simple_pivot_buy",
    "simple_pivot_sell",
    "pivot_breakout_buy",
    "pivot_breakout_sell",
}

TRADE_DE_VALOR_SETUP_DESCRIPTIONS = {
    "landry_buy": (
        "Dave Landry — Compra: MME21 ascendente; candle-sinal com mínima abaixo das duas mínimas anteriores "
        "e tocando/chegando até 1% da MME21; gatilho na máxima e stop R$0,01 abaixo da mínima."
    ),
    "landry_sell": (
        "Dave Landry — Venda: MME21 descendente; candle-sinal com máxima acima das duas máximas anteriores "
        "e tocando/chegando até 1% da MME21; gatilho na mínima e stop R$0,01 acima da máxima."
    ),
    "simple_pivot_buy": (
        "Pivô de Alta Simples: fundo (P1) → topo/cabeça (P2) → novo fundo (P3) que não perde P1; "
        "gatilho na superação de P2. O screener mostra estruturas ARMADAS e pivôs CONFIRMADOS recentemente. "
        "Não exige consolidação, volume ou médias móveis."
    ),
    "simple_pivot_sell": (
        "Pivô de Baixa Simples: topo (P1) → fundo/cabeça (P2) → novo topo (P3) que não supera P1; "
        "gatilho na perda de P2. O screener mostra estruturas ARMADAS e pivôs CONFIRMADOS recentemente. "
        "Não exige consolidação, volume ou médias móveis."
    ),
    "pivot_breakout_buy": (
        "Pivô de Alta / Saída de Consolidação: consolidação de 20 candles, médias curtas comprimidas e volume secando; "
        "rompimento para cima e gatilho na máxima do candle de rompimento. Formalização: faixa <= 12%, "
        "distância média MME9/MME21 <= 2,5% e volume médio dos últimos 5 candles <= média de 20."
    ),
    "pivot_breakout_sell": (
        "Pivô de Baixa / Saída de Consolidação: consolidação de 20 candles, médias curtas comprimidas e volume secando; "
        "rompimento para baixo e gatilho na mínima do candle de rompimento. Formalização: faixa <= 12%, "
        "distância média MME9/MME21 <= 2,5% e volume médio dos últimos 5 candles <= média de 20."
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


def _signal_or_next_bar_state(
    df: pd.DataFrame,
    signal_idx: int,
    side: str,
    name: str,
    stop: float,
    waiting_status: str,
) -> dict:
    last = len(df) - 1
    direction = "Compra" if side == "buy" else "Venda"
    trigger = float(df["High"].iloc[signal_idx] if side == "buy" else df["Low"].iloc[signal_idx])

    if signal_idx == last:
        return _state(
            passed=True,
            name=name,
            status=waiting_status,
            direction=direction,
            signal_date=df.index[signal_idx],
            trigger_date=df.index[signal_idx],
            entry=trigger,
            stop=stop,
        )

    if signal_idx == last - 1:
        invalidated = (
            float(df["Low"].iloc[last]) < stop
            if side == "buy"
            else float(df["High"].iloc[last]) > stop
        )
        if invalidated:
            return _state(
                passed=False,
                name=name,
                status="Setup invalidado antes da entrada",
                direction=direction,
                signal_date=df.index[signal_idx],
                trigger_date=df.index[signal_idx],
                entry=trigger,
                stop=stop,
            )

        broke = (
            float(df["High"].iloc[last]) > trigger
            if side == "buy"
            else float(df["Low"].iloc[last]) < trigger
        )
        return _state(
            passed=True,
            name=name,
            status="Entrada acionada no último candle" if broke else "Setup armado; aguardando gatilho",
            direction=direction,
            signal_date=df.index[signal_idx],
            trigger_date=df.index[signal_idx],
            entry=trigger,
            stop=stop,
        )

    return _state(passed=False, name=name, status="sinal antigo", direction=direction)


def _landry_signal(df: pd.DataFrame, i: int, side: str, proximity_pct: float = 0.01) -> bool:
    if i < 2:
        return False

    close = df["Close"].astype(float)
    e21 = ema(close, 21)
    if not (_finite(e21.iloc[i]) and _finite(e21.iloc[i - 1])):
        return False

    ma = float(e21.iloc[i])
    low = float(df["Low"].iloc[i])
    high = float(df["High"].iloc[i])
    near_ma = low <= ma * (1.0 + proximity_pct) and high >= ma * (1.0 - proximity_pct)

    if side == "buy":
        extreme = low < float(df["Low"].iloc[i - 2:i].min())
        slope_ok = float(e21.iloc[i]) > float(e21.iloc[i - 1])
    else:
        extreme = high > float(df["High"].iloc[i - 2:i].max())
        slope_ok = float(e21.iloc[i]) < float(e21.iloc[i - 1])

    return bool(slope_ok and extreme and near_ma)


def _landry_state(df: pd.DataFrame, side: str) -> dict:
    name = "Dave Landry Compra" if side == "buy" else "Dave Landry Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 25:
        return _state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    last = len(df) - 1
    candidates = [i for i in (last, last - 1) if i >= 2 and _landry_signal(df, i, side)]
    if not candidates:
        return _state(
            passed=False,
            name=name,
            status="sem sinal Landry recente próximo da MME21",
            direction=direction,
        )

    signal_idx = max(candidates)
    stop = (
        float(df["Low"].iloc[signal_idx]) - 0.01
        if side == "buy"
        else float(df["High"].iloc[signal_idx]) + 0.01
    )

    return _signal_or_next_bar_state(
        df,
        signal_idx,
        side,
        name,
        stop,
        "Candle-sinal formado próximo da MME21; aguardando rompimento",
    )


# ---------------------------------------------------------------------------
# PIVÔS SIMPLES
# ---------------------------------------------------------------------------


def _is_swing_low(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    """Fundo local confirmado.

    Aceita empate com um dos vizinhos, desde que seja estritamente menor que o outro.
    Isso evita perder fundos duplos por diferença de apenas um tick.
    """
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["Low"].iloc[i])
    left_min = float(df["Low"].iloc[i - strength:i].astype(float).min())
    right_min = float(df["Low"].iloc[i + 1:i + strength + 1].astype(float).min())
    return bool(value <= left_min and value <= right_min and (value < left_min or value < right_min))


def _is_swing_high(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    """Topo local confirmado, com a mesma tolerância lógica usada nos fundos."""
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["High"].iloc[i])
    left_max = float(df["High"].iloc[i - strength:i].astype(float).max())
    right_max = float(df["High"].iloc[i + 1:i + strength + 1].astype(float).max())
    return bool(value >= left_max and value >= right_max and (value > left_max or value > right_max))


def _alternating_swings(
    df: pd.DataFrame,
    strength: int = 1,
    lookback: int = 160,
) -> list[dict]:
    """Cria uma sequência limpa de swings alternados L/H/L/H.

    Se aparecem dois fundos consecutivos, fica o mais baixo; se aparecem dois topos
    consecutivos, fica o mais alto. Isso evita construir um pivô com pontos internos
    irrelevantes.
    """
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
            if len(cleaned) >= 2 and event["kind"] != cleaned[-2]["kind"]:
                cleaned[-1] = event
            continue

        if not cleaned or event["kind"] != cleaned[-1]["kind"]:
            cleaned.append(event)
            continue

        current = cleaned[-1]
        is_more_extreme = (
            event["value"] < current["value"]
            if event["kind"] == "L"
            else event["value"] > current["value"]
        )
        if is_more_extreme:
            cleaned[-1] = event

    return cleaned


def _simple_pivot_candidates(
    df: pd.DataFrame,
    side: str,
    structure_tolerance_pct: float = 0.003,
) -> list[dict]:
    """Extrai pivôs a partir de três swings consecutivos.

    Compra: L1 -> H1 -> L2, com L2 sem perder L1.
    Venda: H1 -> L1 -> H2, com H2 sem superar H1.

    A tolerância de 0,3% absorve diferenças de um ou poucos ticks em fundos/topos
    praticamente iguais sem transformar uma violação clara em pivô válido.
    """
    swings = _alternating_swings(df)
    candidates: list[dict] = []

    for first, head, second in zip(swings, swings[1:], swings[2:]):
        kinds = (first["kind"], head["kind"], second["kind"])

        if side == "buy" and kinds == ("L", "H", "L"):
            if second["value"] < first["value"] * (1.0 - structure_tolerance_pct):
                continue
            candidates.append(
                {
                    "first_idx": first["idx"],
                    "trigger_idx": head["idx"],
                    "second_idx": second["idx"],
                    "first": first["value"],
                    "entry": head["value"],
                    "stop": second["value"],
                }
            )

        elif side == "sell" and kinds == ("H", "L", "H"):
            if second["value"] > first["value"] * (1.0 + structure_tolerance_pct):
                continue
            candidates.append(
                {
                    "first_idx": first["idx"],
                    "trigger_idx": head["idx"],
                    "second_idx": second["idx"],
                    "first": first["value"],
                    "entry": head["value"],
                    "stop": second["value"],
                }
            )

    return candidates


def _classify_simple_pivot_candidate(
    df: pd.DataFrame,
    structure: dict,
    side: str,
    confirmed_window: int = 10,
    armed_max_age: int = 40,
    stop_tolerance_pct: float = 0.001,
) -> tuple[int, int, dict] | None:
    """Classifica uma estrutura como ARMADA ou CONFIRMADA recentemente."""
    name = "Pivô de Alta Simples" if side == "buy" else "Pivô de Baixa Simples"
    direction = "Compra" if side == "buy" else "Venda"
    second_idx = int(structure["second_idx"])
    trigger_idx = int(structure["trigger_idx"])
    entry = float(structure["entry"])
    stop = float(structure["stop"])
    last = len(df) - 1
    breakout_idx: int | None = None

    for j in range(second_idx + 1, len(df)):
        high = float(df["High"].iloc[j])
        low = float(df["Low"].iloc[j])

        if side == "buy":
            broke = high >= entry
            invalidated_before_entry = low < stop * (1.0 - stop_tolerance_pct)
        else:
            broke = low <= entry
            invalidated_before_entry = high > stop * (1.0 + stop_tolerance_pct)

        if breakout_idx is None:
            if invalidated_before_entry and not broke:
                return None
            if invalidated_before_entry and broke:
                return None
            if broke:
                breakout_idx = j

    signal_date = df.index[second_idx]
    trigger_date = df.index[trigger_idx]
    close_now = float(df["Close"].iloc[-1])

    if breakout_idx is not None:
        age = last - breakout_idx
        if age > confirmed_window:
            return None

        current_structure_ok = (
            close_now >= stop * (1.0 - stop_tolerance_pct)
            if side == "buy"
            else close_now <= stop * (1.0 + stop_tolerance_pct)
        )
        if not current_structure_ok:
            return None

        distance_pct = (
            (close_now / entry - 1.0) * 100.0
            if side == "buy"
            else (entry / close_now - 1.0) * 100.0
        )
        age_text = "no último candle" if age == 0 else f"há {age} candle{'s' if age != 1 else ''}"
        structure_text = (
            f"P1/fundo {structure['first']:.2f} · P2/gatilho {entry:.2f} · P3/stop {stop:.2f}"
            if side == "buy"
            else f"P1/topo {structure['first']:.2f} · P2/gatilho {entry:.2f} · P3/stop {stop:.2f}"
        )
        return (
            breakout_idx,
            2,
            _state(
                passed=True,
                name=name,
                status=(
                    f"CONFIRMADO {age_text}; {structure_text}; "
                    f"fechamento atual {close_now:.2f} ({distance_pct:+.1f}% vs gatilho)"
                ),
                direction=direction,
                signal_date=signal_date,
                trigger_date=trigger_date,
                entry=entry,
                stop=stop,
            ),
        )

    setup_age = last - second_idx
    if setup_age > armed_max_age:
        return None

    if side == "buy":
        min_since_second = float(df["Low"].iloc[second_idx:].min())
        if min_since_second < stop * (1.0 - stop_tolerance_pct):
            return None
        distance_to_trigger = (entry / close_now - 1.0) * 100.0
        structure_text = (
            f"P1/fundo {structure['first']:.2f} · P2/gatilho {entry:.2f} · P3/stop {stop:.2f}"
        )
    else:
        max_since_second = float(df["High"].iloc[second_idx:].max())
        if max_since_second > stop * (1.0 + stop_tolerance_pct):
            return None
        distance_to_trigger = (close_now / entry - 1.0) * 100.0
        structure_text = (
            f"P1/topo {structure['first']:.2f} · P2/gatilho {entry:.2f} · P3/stop {stop:.2f}"
        )

    return (
        second_idx,
        1,
        _state(
            passed=True,
            name=name,
            status=(
                f"ARMADO; {structure_text}; "
                f"{abs(distance_to_trigger):.1f}% até o gatilho"
            ),
            direction=direction,
            signal_date=signal_date,
            trigger_date=trigger_date,
            entry=entry,
            stop=stop,
        ),
    )


def _simple_pivot_state(df: pd.DataFrame, side: str) -> dict:
    name = "Pivô de Alta Simples" if side == "buy" else "Pivô de Baixa Simples"
    direction = "Compra" if side == "buy" else "Venda"

    if len(df) < 7:
        return _state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    candidates = _simple_pivot_candidates(df, side)
    if not candidates:
        return _state(
            passed=False,
            name=name,
            status="nenhuma sequência estrutural de pivô encontrada na janela recente",
            direction=direction,
        )

    classified = []
    for structure in candidates:
        item = _classify_simple_pivot_candidate(df, structure, side)
        if item is not None:
            classified.append(item)

    if not classified:
        return _state(
            passed=False,
            name=name,
            status=(
                f"{len(candidates)} estrutura(s) de pivô encontradas, mas nenhuma está "
                "armada ou confirmada dentro das janelas atuais"
            ),
            direction=direction,
        )

    _, _, best_state = max(classified, key=lambda item: (item[0], item[1]))
    return best_state


# ---------------------------------------------------------------------------
# PIVÔ / SAÍDA DE CONSOLIDAÇÃO
# ---------------------------------------------------------------------------


def _pivot_signal(df: pd.DataFrame, i: int, side: str, lookback: int = 20) -> tuple[bool, dict]:
    if i < lookback + 2:
        return False, {}

    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    prior = df.iloc[i - lookback:i]
    resistance = float(prior["High"].max())
    support = float(prior["Low"].min())
    reference_price = float(close.iloc[i - 1])
    if reference_price <= 0:
        return False, {}

    band_pct = (resistance - support) / reference_price
    spreads = []
    for j in range(i - 5, i):
        if _finite(e9.iloc[j]) and _finite(e21.iloc[j]) and float(close.iloc[j]) != 0:
            spreads.append(abs(float(e9.iloc[j]) - float(e21.iloc[j])) / abs(float(close.iloc[j])))
    mean_spread = sum(spreads) / len(spreads) if spreads else float("inf")

    avg5 = float(volume.iloc[i - 5:i].mean())
    avg20 = float(volume.iloc[i - lookback:i].mean())
    dry_volume = _finite(avg5) and _finite(avg20) and avg20 > 0 and avg5 <= avg20
    compressed = band_pct <= 0.12 and mean_spread <= 0.025 and dry_volume

    if side == "buy":
        breakout = float(close.iloc[i]) > resistance
    else:
        breakout = float(close.iloc[i]) < support

    vol_ratio = float(volume.iloc[i]) / avg20 if avg20 > 0 else float("nan")
    return bool(compressed and breakout), {
        "resistance": resistance,
        "support": support,
        "band_pct": band_pct,
        "mean_spread": mean_spread,
        "vol_ratio": vol_ratio,
    }


def _pivot_state(df: pd.DataFrame, side: str) -> dict:
    name = "Pivô de Alta / Saída de Consolidação" if side == "buy" else "Pivô de Baixa / Saída de Consolidação"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 25:
        return _state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    last = len(df) - 1
    found = []
    for i in (last, last - 1):
        ok, meta = _pivot_signal(df, i, side)
        if ok:
            found.append((i, meta))
    if not found:
        return _state(passed=False, name=name, status="sem rompimento de consolidação recente", direction=direction)

    signal_idx, meta = max(found, key=lambda item: item[0])
    stop = float(df["Low"].iloc[signal_idx] if side == "buy" else df["High"].iloc[signal_idx])
    vol_ratio = meta.get("vol_ratio")
    catalyst = f"; volume do rompimento {vol_ratio:.1f}x a média de 20" if _finite(vol_ratio) else ""

    return _signal_or_next_bar_state(
        df,
        signal_idx,
        side,
        name,
        stop,
        f"Rompimento da consolidação formado{catalyst}; aguardando gatilho",
    )


def trade_de_valor_setup_state(df: pd.DataFrame, op: str) -> dict:
    if op == "landry_buy":
        return _landry_state(df, "buy")
    if op == "landry_sell":
        return _landry_state(df, "sell")
    if op == "simple_pivot_buy":
        return _simple_pivot_state(df, "buy")
    if op == "simple_pivot_sell":
        return _simple_pivot_state(df, "sell")
    if op == "pivot_breakout_buy":
        return _pivot_state(df, "buy")
    if op == "pivot_breakout_sell":
        return _pivot_state(df, "sell")
    raise ValueError(f"Setup Trade de Valor não suportado: {op}")


def trade_de_valor_setup_description(op: str) -> str:
    return TRADE_DE_VALOR_SETUP_DESCRIPTIONS.get(op, op)
