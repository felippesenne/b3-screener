from __future__ import annotations

import math

import pandas as pd

from indicators import sma


MOMENTUM_205080_OPS = {"momentum_205080_buy", "momentum_205080_sell"}

MOMENTUM_205080_DESCRIPTIONS = {
    "momentum_205080_buy": (
        "Momentum 20/50/80 — Compra: MMS20, MMS50 e MMS80 ascendentes, estrutura de topos e fundos "
        "ascendentes e candle-sinal próximo da MMS20 cuja mínima perde as duas mínimas anteriores. "
        "Entrada R$0,01 acima da máxima; se não acionar, o gatilho acompanha a máxima dos candles seguintes "
        "enquanto as três médias seguirem ascendentes. Stop R$0,01 abaixo da mínima do candle-sinal e alvo em 2R."
    ),
    "momentum_205080_sell": (
        "Momentum 20/50/80 — Venda: MMS20, MMS50 e MMS80 descendentes, estrutura de topos e fundos "
        "descendentes e candle-sinal próximo da MMS20 cuja máxima supera as duas máximas anteriores. "
        "Entrada R$0,01 abaixo da mínima; se não acionar, o gatilho acompanha a mínima dos candles seguintes "
        "enquanto as três médias seguirem descendentes. Stop R$0,01 acima da máxima do candle-sinal e alvo em 2R."
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
    direction: str,
    signal_date=None,
    trigger_date=None,
    entry: float | None = None,
    stop: float | None = None,
    target_2r: float | None = None,
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
        "target_2r": target_2r,
    }


def _is_swing_low(df: pd.DataFrame, i: int) -> bool:
    if i < 1 or i + 1 >= len(df):
        return False
    value = float(df["Low"].iloc[i])
    left = float(df["Low"].iloc[i - 1])
    right = float(df["Low"].iloc[i + 1])
    return value <= left and value <= right and (value < left or value < right)


def _is_swing_high(df: pd.DataFrame, i: int) -> bool:
    if i < 1 or i + 1 >= len(df):
        return False
    value = float(df["High"].iloc[i])
    left = float(df["High"].iloc[i - 1])
    right = float(df["High"].iloc[i + 1])
    return value >= left and value >= right and (value > left or value > right)


def _alternating_swings(df: pd.DataFrame, lookback: int = 90) -> list[dict]:
    if len(df) < 5:
        return []
    start = max(1, len(df) - lookback)
    raw: list[dict] = []
    for i in range(start, len(df) - 1):
        if _is_swing_low(df, i):
            raw.append({"idx": i, "kind": "L", "value": float(df["Low"].iloc[i])})
        if _is_swing_high(df, i):
            raw.append({"idx": i, "kind": "H", "value": float(df["High"].iloc[i])})

    raw.sort(key=lambda event: (event["idx"], event["kind"]))
    cleaned: list[dict] = []
    for event in raw:
        if cleaned and event["idx"] == cleaned[-1]["idx"]:
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


def _structure_ok(df: pd.DataFrame, i: int, side: str) -> bool:
    # Usa somente informação disponível até o candle avaliado. O candle atual ainda
    # não pode ser um swing confirmado porque não há candle futuro para confirmá-lo.
    swings = _alternating_swings(df.iloc[: i + 1])
    highs = [event for event in swings if event["kind"] == "H"]
    lows = [event for event in swings if event["kind"] == "L"]
    if len(highs) < 2 or len(lows) < 2:
        return False

    if side == "buy":
        return highs[-1]["value"] > highs[-2]["value"] and lows[-1]["value"] > lows[-2]["value"]
    return highs[-1]["value"] < highs[-2]["value"] and lows[-1]["value"] < lows[-2]["value"]


def _moving_averages(df: pd.DataFrame):
    close = df["Close"].astype(float)
    return sma(close, 20), sma(close, 50), sma(close, 80)


def _averages_direction_ok(m20: pd.Series, m50: pd.Series, m80: pd.Series, i: int, side: str) -> bool:
    if i < 1:
        return False
    values = [m20.iloc[i], m20.iloc[i - 1], m50.iloc[i], m50.iloc[i - 1], m80.iloc[i], m80.iloc[i - 1]]
    if not all(_finite(value) for value in values):
        return False
    if side == "buy":
        return m20.iloc[i] > m20.iloc[i - 1] and m50.iloc[i] > m50.iloc[i - 1] and m80.iloc[i] > m80.iloc[i - 1]
    return m20.iloc[i] < m20.iloc[i - 1] and m50.iloc[i] < m50.iloc[i - 1] and m80.iloc[i] < m80.iloc[i - 1]


def _near_sma20(df: pd.DataFrame, m20: pd.Series, i: int, max_distance_pct: float = 0.02) -> bool:
    if not _finite(m20.iloc[i]) or float(m20.iloc[i]) == 0:
        return False
    ma = float(m20.iloc[i])
    low = float(df["Low"].iloc[i])
    high = float(df["High"].iloc[i])
    if low <= ma <= high:
        return True
    distance = min(abs(low - ma), abs(high - ma)) / abs(ma)
    return distance <= max_distance_pct


def _signal_ok(df: pd.DataFrame, m20: pd.Series, m50: pd.Series, m80: pd.Series, i: int, side: str) -> bool:
    if i < 2 or not _averages_direction_ok(m20, m50, m80, i, side):
        return False
    if not _structure_ok(df, i, side) or not _near_sma20(df, m20, i):
        return False
    if side == "buy":
        return float(df["Low"].iloc[i]) < float(df["Low"].iloc[i - 2:i].min())
    return float(df["High"].iloc[i]) > float(df["High"].iloc[i - 2:i].max())


def _higher_timeframe_status(df: pd.DataFrame, side: str) -> str:
    if len(df) < 3:
        return "TF maior: histórico insuficiente"
    deltas = df.index.to_series().diff().dropna().dt.total_seconds() / 86400.0
    median_days = float(deltas.median()) if not deltas.empty else 1.0
    if median_days <= 3:
        rule, label = "W-FRI", "Semanal"
    elif median_days <= 10:
        rule, label = "ME", "Mensal"
    else:
        rule, label = "QE", "Trimestral"

    higher = df.resample(rule).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    ).dropna(subset=["Close"])
    if len(higher) < 81:
        return f"TF maior ({label}): histórico insuficiente para MMS80"

    h20, h50, h80 = _moving_averages(higher)
    aligned = _averages_direction_ok(h20, h50, h80, len(higher) - 1, side)
    return f"TF maior ({label}): {'alinhado' if aligned else 'não alinhado'}"


def _target_2r(side: str, entry: float, stop: float) -> float:
    risk = abs(entry - stop)
    return entry + 2.0 * risk if side == "buy" else entry - 2.0 * risk


def _setup_state(df: pd.DataFrame, side: str, confirmed_window: int = 3) -> dict:
    name = "Momentum 20/50/80 — Compra" if side == "buy" else "Momentum 20/50/80 — Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 82:
        return _state(
            passed=False,
            name=name,
            status="sem dados suficientes para MMS80 e estrutura",
            direction=direction,
        )

    m20, m50, m80 = _moving_averages(df)
    signals = [i for i in range(80, len(df)) if _signal_ok(df, m20, m50, m80, i, side)]
    if not signals:
        return _state(
            passed=False,
            name=name,
            status="sem candle-sinal que combine tendência, estrutura e proximidade da MMS20",
            direction=direction,
        )

    signal_idx = signals[-1]
    last = len(df) - 1
    tick = 0.01
    if side == "buy":
        stop = float(df["Low"].iloc[signal_idx]) - tick
        trigger = float(df["High"].iloc[signal_idx]) + tick
    else:
        stop = float(df["High"].iloc[signal_idx]) + tick
        trigger = float(df["Low"].iloc[signal_idx]) - tick
    trigger_idx = signal_idx
    entry_idx = None
    actual_entry = None

    for j in range(signal_idx + 1, len(df)):
        high = float(df["High"].iloc[j])
        low = float(df["Low"].iloc[j])
        if side == "buy":
            invalidated = low <= stop
            broke = high >= trigger
        else:
            invalidated = high >= stop
            broke = low <= trigger

        # Se stop e gatilho ocorrerem no mesmo candle, a ordem intrabar é desconhecida.
        # O screener adota a leitura conservadora e invalida a estrutura.
        if invalidated:
            return _state(
                passed=False,
                name=name,
                status="setup invalidado pelo stop antes de uma entrada inequívoca",
                direction=direction,
                signal_date=df.index[signal_idx],
                trigger_date=df.index[trigger_idx],
                entry=trigger,
                stop=stop,
                target_2r=_target_2r(side, trigger, stop),
            )

        if broke:
            entry_idx = j
            actual_entry = trigger
            break

        if not _averages_direction_ok(m20, m50, m80, j, side):
            return _state(
                passed=False,
                name=name,
                status="setup cancelado: uma das MMS20/50/80 perdeu a inclinação exigida antes da entrada",
                direction=direction,
                signal_date=df.index[signal_idx],
                trigger_date=df.index[trigger_idx],
                entry=trigger,
                stop=stop,
                target_2r=_target_2r(side, trigger, stop),
            )

        trigger_idx = j
        trigger = (high + tick) if side == "buy" else (low - tick)

    higher_status = _higher_timeframe_status(df, side)

    if entry_idx is None:
        target = _target_2r(side, trigger, stop)
        return _state(
            passed=True,
            name=name,
            status=(
                f"ARMADO; MMS20/50/80 {'↑' if side == 'buy' else '↓'}; "
                f"estrutura {'ascendente' if side == 'buy' else 'descendente'}; "
                f"gatilho {trigger:.2f}; stop {stop:.2f}; alvo 2R {target:.2f}; {higher_status}"
            ),
            direction=direction,
            signal_date=df.index[signal_idx],
            trigger_date=df.index[trigger_idx],
            entry=trigger,
            stop=stop,
            target_2r=target,
        )

    age = last - entry_idx
    target = _target_2r(side, actual_entry, stop)
    if age > confirmed_window:
        return _state(
            passed=False,
            name=name,
            status=f"entrada já acionada há {age} candles; fora da janela de confirmação recente",
            direction=direction,
            signal_date=df.index[signal_idx],
            trigger_date=df.index[trigger_idx],
            entry=actual_entry,
            stop=stop,
            target_2r=target,
        )

    age_text = "no último candle" if age == 0 else f"há {age} candle{'s' if age != 1 else ''}"
    return _state(
        passed=True,
        name=name,
        status=(
            f"CONFIRMADO {age_text}; entrada {actual_entry:.2f}; stop {stop:.2f}; "
            f"alvo 2R {target:.2f}; {higher_status}"
        ),
        direction=direction,
        signal_date=df.index[signal_idx],
        trigger_date=df.index[trigger_idx],
        entry=actual_entry,
        stop=stop,
        target_2r=target,
    )


def momentum_205080_state(df: pd.DataFrame, op: str) -> dict:
    if op == "momentum_205080_buy":
        return _setup_state(df, "buy")
    if op == "momentum_205080_sell":
        return _setup_state(df, "sell")
    raise ValueError(f"Setup Momentum 20/50/80 não suportado: {op}")


def momentum_205080_description(op: str) -> str:
    return MOMENTUM_205080_DESCRIPTIONS.get(op, op)
