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
        "Pivô de Alta Simples: fundo anterior, topo intermediário e novo fundo mais alto. "
        "O setup aparece enquanto estiver armado e também por até 5 candles após a confirmação pelo rompimento do topo. "
        "Stop estrutural no fundo mais alto. Não exige consolidação, volume ou médias móveis."
    ),
    "simple_pivot_sell": (
        "Pivô de Baixa Simples: topo anterior, fundo intermediário e novo topo mais baixo. "
        "O setup aparece enquanto estiver armado e também por até 5 candles após a confirmação pela perda do fundo. "
        "Stop estrutural no topo mais baixo. Não exige consolidação, volume ou médias móveis."
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


def _is_swing_low(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    """Fundo local confirmado, aceitando empate com um dos vizinhos.

    Exige que a mínima seja menor ou igual às mínimas da vizinhança e estritamente
    menor que pelo menos um lado. Isso reconhece fundos duplos sem transformar uma
    sequência totalmente plana em vários swings.
    """
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["Low"].iloc[i])
    left_min = float(df["Low"].iloc[i - strength:i].astype(float).min())
    right_min = float(df["Low"].iloc[i + 1:i + strength + 1].astype(float).min())
    return bool(value <= left_min and value <= right_min and (value < left_min or value < right_min))


def _is_swing_high(df: pd.DataFrame, i: int, strength: int = 1) -> bool:
    """Topo local confirmado, aceitando empate com um dos vizinhos."""
    if i < strength or i + strength >= len(df):
        return False
    value = float(df["High"].iloc[i])
    left_max = float(df["High"].iloc[i - strength:i].astype(float).max())
    right_max = float(df["High"].iloc[i + 1:i + strength + 1].astype(float).max())
    return bool(value >= left_max and value >= right_max and (value > left_max or value > right_max))


def _simple_pivot_candidates(
    df: pd.DataFrame,
    side: str,
    strength: int = 1,
    lookback: int = 120,
) -> list[dict]:
    """Retorna estruturas clássicas de pivô ordenadas cronologicamente.

    Compra: fundo 1 -> topo intermediário -> fundo 2 mais alto.
    Venda: topo 1 -> fundo intermediário -> topo 2 mais baixo.
    """
    if len(df) < 7:
        return []

    start = max(strength, len(df) - lookback)
    end = len(df) - strength
    lows = [i for i in range(start, end) if _is_swing_low(df, i, strength)]
    highs = [i for i in range(start, end) if _is_swing_high(df, i, strength)]
    candidates: list[dict] = []

    if side == "buy":
        for low2_idx in lows:
            prior_highs = [i for i in highs if i < low2_idx]
            if not prior_highs:
                continue
            high1_idx = prior_highs[-1]
            prior_lows = [i for i in lows if i < high1_idx]
            if not prior_lows:
                continue
            low1_idx = prior_lows[-1]
            low1 = float(df["Low"].iloc[low1_idx])
            low2 = float(df["Low"].iloc[low2_idx])
            if low2 <= low1:
                continue
            candidates.append(
                {
                    "first_idx": low1_idx,
                    "trigger_idx": high1_idx,
                    "second_idx": low2_idx,
                    "first": low1,
                    "trigger": float(df["High"].iloc[high1_idx]),
                    "second": low2,
                    "entry": float(df["High"].iloc[high1_idx]),
                    "stop": low2,
                }
            )
    else:
        for high2_idx in highs:
            prior_lows = [i for i in lows if i < high2_idx]
            if not prior_lows:
                continue
            low1_idx = prior_lows[-1]
            prior_highs = [i for i in highs if i < low1_idx]
            if not prior_highs:
                continue
            high1_idx = prior_highs[-1]
            high1 = float(df["High"].iloc[high1_idx])
            high2 = float(df["High"].iloc[high2_idx])
            if high2 >= high1:
                continue
            candidates.append(
                {
                    "first_idx": high1_idx,
                    "trigger_idx": low1_idx,
                    "second_idx": high2_idx,
                    "first": high1,
                    "trigger": float(df["Low"].iloc[low1_idx]),
                    "second": high2,
                    "entry": float(df["Low"].iloc[low1_idx]),
                    "stop": high2,
                }
            )

    return candidates


def _classify_simple_pivot_candidate(
    df: pd.DataFrame,
    structure: dict,
    side: str,
    confirmed_window: int,
    armed_max_age: int,
) -> tuple[int, int, dict] | None:
    """Classifica um pivô como armado ou confirmado recentemente.

    Retorna (índice do evento mais recente, prioridade, estado). Confirmados recebem
    prioridade maior que armados quando o evento ocorreu no mesmo candle.
    """
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
            broke = high > entry
            invalidated = low < stop
        else:
            broke = low < entry
            invalidated = high > stop

        if breakout_idx is None:
            if broke and invalidated:
                return None
            if invalidated:
                return None
            if broke:
                breakout_idx = j
                continue
        elif invalidated:
            # Pivô chegou a confirmar, mas o stop estrutural foi perdido depois.
            return None

    signal_date = df.index[second_idx]
    trigger_date = df.index[trigger_idx]

    if breakout_idx is not None:
        age = last - breakout_idx
        if age > confirmed_window:
            return None

        close_now = float(df["Close"].iloc[-1])
        distance_pct = (
            (close_now / entry - 1.0) * 100.0
            if side == "buy"
            else (entry / close_now - 1.0) * 100.0
        )
        age_text = "no último candle" if age == 0 else f"há {age} candle{'s' if age != 1 else ''}"
        structure_text = (
            f"fundo1 {structure['first']:.2f} · topo/gatilho {entry:.2f} · fundo2/stop {stop:.2f}"
            if side == "buy"
            else f"topo1 {structure['first']:.2f} · fundo/gatilho {entry:.2f} · topo2/stop {stop:.2f}"
        )
        status = (
            f"CONFIRMADO {age_text}; {structure_text}; "
            f"fechamento atual {close_now:.2f} ({distance_pct:+.1f}% vs gatilho)"
        )
        return (
            breakout_idx,
            2,
            _state(
                passed=True,
                name=name,
                status=status,
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

    structure_text = (
        f"fundo1 {structure['first']:.2f} · topo/gatilho {entry:.2f} · fundo2/stop {stop:.2f}"
        if side == "buy"
        else f"topo1 {structure['first']:.2f} · fundo/gatilho {entry:.2f} · topo2/stop {stop:.2f}"
    )
    status = (
        f"ARMADO; {structure_text}; aguardando "
        f"{'rompimento do topo' if side == 'buy' else 'perda do fundo'}"
    )
    return (
        second_idx,
        1,
        _state(
            passed=True,
            name=name,
            status=status,
            direction=direction,
            signal_date=signal_date,
            trigger_date=trigger_date,
            entry=entry,
            stop=stop,
        ),
    )


def _simple_pivot_state(
    df: pd.DataFrame,
    side: str,
    confirmed_window: int = 5,
    armed_max_age: int = 20,
) -> dict:
    """Seleciona pivôs armados ou confirmados recentemente.

    - Estruturas confirmadas continuam aparecendo por até 5 candles após o rompimento.
    - Estruturas ainda armadas podem permanecer por até 20 candles após o segundo swing.
    - Se o stop estrutural for perdido antes ou depois do rompimento, a estrutura deixa de valer.
    - Entre múltiplos pivôs, prevalece o evento relevante mais recente.
    """
    name = "Pivô de Alta Simples" if side == "buy" else "Pivô de Baixa Simples"
    direction = "Compra" if side == "buy" else "Venda"
    candidates = _simple_pivot_candidates(df, side)
    if not candidates:
        return _state(passed=False, name=name, status="sem estrutura de pivô recente", direction=direction)

    classified = []
    for structure in candidates:
        item = _classify_simple_pivot_candidate(
            df,
            structure,
            side,
            confirmed_window=confirmed_window,
            armed_max_age=armed_max_age,
        )
        if item is not None:
            classified.append(item)

    if not classified:
        return _state(
            passed=False,
            name=name,
            status=(
                f"sem pivô armado nos últimos {armed_max_age} candles nem confirmação válida "
                f"nos últimos {confirmed_window} candles"
            ),
            direction=direction,
        )

    _, _, best_state = max(classified, key=lambda item: (item[0], item[1]))
    return best_state


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
