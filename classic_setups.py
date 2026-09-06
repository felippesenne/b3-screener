from __future__ import annotations

import math

import pandas as pd

from indicators import ema


SPECIAL_SETUP_OPS = {
    "pfr_buy",
    "pfr_sell",
    "setup_123_buy",
    "setup_123_sell",
    "setup_92_buy",
    "setup_92_sell",
    "setup_93_buy",
    "setup_93_sell",
    "ifr2_stormer",
    "inside_bar",
}

SPECIAL_SETUP_DESCRIPTIONS = {
    "pfr_buy": "Stormer — PFR Compra: mínima inferior às duas anteriores e fechamento acima do fechamento anterior; gatilho no rompimento da máxima do candle-sinal",
    "pfr_sell": "Stormer — PFR Venda: máxima superior às duas anteriores e fechamento abaixo do fechamento anterior; gatilho na perda da mínima do candle-sinal",
    "setup_123_buy": "Stormer — Setup 123 Compra: fundo de 3 candles com o candle 2 na menor mínima e candle 3 de alta; gatilho acima da máxima do candle 3",
    "setup_123_sell": "Stormer — Setup 123 Venda: topo de 3 candles com o candle 2 na maior máxima e candle 3 de baixa; gatilho abaixo da mínima do candle 3",
    "setup_92_buy": "Larry Williams — Setup 9.2 Compra: MME9 ascendente, fechamento abaixo da mínima do candle anterior e entrada no rompimento da máxima do candle marcado",
    "setup_92_sell": "Larry Williams — Setup 9.2 Venda: MME9 descendente, fechamento acima da máxima do candle anterior e entrada na perda da mínima do candle marcado",
    "setup_93_buy": "Larry Williams — Setup 9.3 Compra: MME9 ascendente e dois fechamentos consecutivos descendentes após candle de referência; gatilho na máxima do último candle",
    "setup_93_sell": "Larry Williams — Setup 9.3 Venda: MME9 descendente e dois fechamentos consecutivos ascendentes após candle de referência; gatilho na mínima do último candle",
    "ifr2_stormer": "Stormer — IFR2 clássico: IFR(2) abaixo de 5, entrada no fechamento do candle e stop de referência na expansão de 130% da amplitude",
    "inside_bar": "Inside Bar: candle atual completamente dentro da máxima e mínima do candle anterior",
}

CONTEXT_FILTERS = [
    "Éden dos Traders — Compra",
    "Éden dos Traders — Venda",
    "MME80 ascendente",
    "MME80 descendente",
    "Stormer MME49 — Compra",
    "Stormer MME49 — Venda",
    "Preço acima da MME200",
    "Preço abaixo da MME200",
    "Inside Bar atual",
]


def _finite(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except Exception:
        return False


def _base_state(
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


def _pfr_signal(df: pd.DataFrame, i: int, side: str, lookback: int = 2) -> bool:
    if i < lookback:
        return False
    if side == "buy":
        return (
            float(df["Low"].iloc[i]) < float(df["Low"].iloc[i - lookback:i].min())
            and float(df["Close"].iloc[i]) > float(df["Close"].iloc[i - 1])
        )
    return (
        float(df["High"].iloc[i]) > float(df["High"].iloc[i - lookback:i].max())
        and float(df["Close"].iloc[i]) < float(df["Close"].iloc[i - 1])
    )


def _pfr_state(df: pd.DataFrame, side: str) -> dict:
    name = "PFR Compra" if side == "buy" else "PFR Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 3:
        return _base_state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    last = len(df) - 1
    if _pfr_signal(df, last, side):
        entry = float(df["High"].iloc[last] if side == "buy" else df["Low"].iloc[last])
        stop = float(df["Low"].iloc[last] if side == "buy" else df["High"].iloc[last])
        return _base_state(
            passed=True,
            name=name,
            status="Candle-sinal formado; aguardando o próximo candle",
            direction=direction,
            signal_date=df.index[last],
            trigger_date=df.index[last],
            entry=entry,
            stop=stop,
        )

    previous = last - 1
    if previous >= 2 and _pfr_signal(df, previous, side):
        trigger = float(df["High"].iloc[previous] if side == "buy" else df["Low"].iloc[previous])
        stop = float(df["Low"].iloc[previous] if side == "buy" else df["High"].iloc[previous])
        broke = (
            float(df["High"].iloc[last]) > trigger
            if side == "buy"
            else float(df["Low"].iloc[last]) < trigger
        )
        return _base_state(
            passed=broke,
            name=name,
            status="Entrada acionada no último candle" if broke else "Gatilho não rompido no candle seguinte",
            direction=direction,
            signal_date=df.index[previous],
            trigger_date=df.index[previous],
            entry=trigger,
            stop=stop,
        )

    return _base_state(passed=False, name=name, status="sem PFR recente", direction=direction)


def _setup_123_signal(df: pd.DataFrame, i: int, side: str) -> bool:
    if i < 2:
        return False
    c1, c2, c3 = i - 2, i - 1, i
    if side == "buy":
        return (
            float(df["Low"].iloc[c2]) < float(df["Low"].iloc[c1])
            and float(df["Low"].iloc[c2]) < float(df["Low"].iloc[c3])
            and float(df["Close"].iloc[c3]) > float(df["Open"].iloc[c3])
        )
    return (
        float(df["High"].iloc[c2]) > float(df["High"].iloc[c1])
        and float(df["High"].iloc[c2]) > float(df["High"].iloc[c3])
        and float(df["Close"].iloc[c3]) < float(df["Open"].iloc[c3])
    )


def _setup_123_state(df: pd.DataFrame, side: str) -> dict:
    name = "Setup 123 Compra" if side == "buy" else "Setup 123 Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 3:
        return _base_state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    last = len(df) - 1
    if _setup_123_signal(df, last, side):
        c2 = last - 1
        entry = float(df["High"].iloc[last] if side == "buy" else df["Low"].iloc[last])
        stop = float(df["Low"].iloc[c2] if side == "buy" else df["High"].iloc[c2])
        return _base_state(
            passed=True,
            name=name,
            status="Padrão 123 formado; aguardando rompimento do candle 3",
            direction=direction,
            signal_date=df.index[last],
            trigger_date=df.index[last],
            entry=entry,
            stop=stop,
        )

    previous = last - 1
    if previous >= 2 and _setup_123_signal(df, previous, side):
        c2 = previous - 1
        trigger = float(df["High"].iloc[previous] if side == "buy" else df["Low"].iloc[previous])
        stop = float(df["Low"].iloc[c2] if side == "buy" else df["High"].iloc[c2])
        broke = (
            float(df["High"].iloc[last]) > trigger
            if side == "buy"
            else float(df["Low"].iloc[last]) < trigger
        )
        return _base_state(
            passed=broke,
            name=name,
            status="Entrada acionada no último candle" if broke else "Padrão formado, mas gatilho ainda não acionado",
            direction=direction,
            signal_date=df.index[previous],
            trigger_date=df.index[previous],
            entry=trigger,
            stop=stop,
        )

    return _base_state(passed=False, name=name, status="sem padrão 123 recente", direction=direction)


def _ema_direction_ok(ema9: pd.Series, i: int, side: str) -> bool:
    if i < 1 or not (_finite(ema9.iloc[i - 1]) and _finite(ema9.iloc[i])):
        return False
    return float(ema9.iloc[i]) > float(ema9.iloc[i - 1]) if side == "buy" else float(ema9.iloc[i]) < float(ema9.iloc[i - 1])


def _setup_92_signal(df: pd.DataFrame, ema9: pd.Series, i: int, side: str) -> bool:
    if i < 1 or not _ema_direction_ok(ema9, i, side):
        return False
    if side == "buy":
        return float(df["Close"].iloc[i]) < float(df["Low"].iloc[i - 1])
    return float(df["Close"].iloc[i]) > float(df["High"].iloc[i - 1])


def _rolling_trigger_state(
    df: pd.DataFrame,
    ema9: pd.Series,
    signal_idx: int,
    side: str,
    name: str,
    initial_stop: float | None = None,
) -> dict:
    direction = "Compra" if side == "buy" else "Venda"
    last = len(df) - 1
    trigger_idx = signal_idx
    trigger = float(df["High"].iloc[signal_idx] if side == "buy" else df["Low"].iloc[signal_idx])
    stop = float(
        initial_stop
        if initial_stop is not None
        else (df["Low"].iloc[signal_idx] if side == "buy" else df["High"].iloc[signal_idx])
    )

    if signal_idx == last:
        return _base_state(
            passed=True,
            name=name,
            status="Candle-sinal formado",
            direction=direction,
            signal_date=df.index[signal_idx],
            trigger_date=df.index[trigger_idx],
            entry=trigger,
            stop=stop,
        )

    for j in range(signal_idx + 1, len(df)):
        broke = (
            float(df["High"].iloc[j]) > trigger
            if side == "buy"
            else float(df["Low"].iloc[j]) < trigger
        )
        if broke:
            return _base_state(
                passed=j == last,
                name=name,
                status="Entrada acionada no último candle" if j == last else "Entrada já acionada anteriormente",
                direction=direction,
                signal_date=df.index[signal_idx],
                trigger_date=df.index[trigger_idx],
                entry=trigger,
                stop=stop,
            )

        if not _ema_direction_ok(ema9, j, side):
            return _base_state(
                passed=False,
                name=name,
                status=f"MME9 perdeu a inclinação de {direction.lower()} antes da entrada",
                direction=direction,
                signal_date=df.index[signal_idx],
                trigger_date=df.index[trigger_idx],
                entry=trigger,
                stop=stop,
            )

        trigger_idx = j
        trigger = float(df["High"].iloc[j] if side == "buy" else df["Low"].iloc[j])
        if side == "buy":
            stop = min(stop, float(df["Low"].iloc[j]))
        else:
            stop = max(stop, float(df["High"].iloc[j]))

    return _base_state(
        passed=True,
        name=name,
        status="Aguardando rompimento",
        direction=direction,
        signal_date=df.index[signal_idx],
        trigger_date=df.index[trigger_idx],
        entry=trigger,
        stop=stop,
    )


def _setup_92_state(df: pd.DataFrame, ema9: pd.Series, side: str) -> dict:
    name = "Setup 9.2 Compra" if side == "buy" else "Setup 9.2 Venda"
    if len(df) < 3:
        return _base_state(passed=False, name=name, status="sem dados suficientes")

    signals = [i for i in range(1, len(df)) if _setup_92_signal(df, ema9, i, side)]
    if not signals:
        return _base_state(passed=False, name=name, status="sem sinal 9.2 recente")
    return _rolling_trigger_state(df, ema9, signals[-1], side, name)


def _setup_93_signal(df: pd.DataFrame, ema9: pd.Series, i: int, side: str) -> bool:
    if i < 2 or not _ema_direction_ok(ema9, i, side):
        return False
    ref, first, second = i - 2, i - 1, i
    if side == "buy":
        return (
            float(df["Close"].iloc[first]) < float(df["Close"].iloc[ref])
            and float(df["Close"].iloc[second]) < float(df["Close"].iloc[first])
            and float(df["Close"].iloc[first]) >= float(df["Low"].iloc[ref])
        )
    return (
        float(df["Close"].iloc[first]) > float(df["Close"].iloc[ref])
        and float(df["Close"].iloc[second]) > float(df["Close"].iloc[first])
        and float(df["Close"].iloc[first]) <= float(df["High"].iloc[ref])
    )


def _setup_93_state(df: pd.DataFrame, ema9: pd.Series, side: str) -> dict:
    name = "Setup 9.3 Compra" if side == "buy" else "Setup 9.3 Venda"
    if len(df) < 4:
        return _base_state(passed=False, name=name, status="sem dados suficientes")

    signals = [i for i in range(2, len(df)) if _setup_93_signal(df, ema9, i, side)]
    if not signals:
        return _base_state(passed=False, name=name, status="sem sinal 9.3 recente")

    signal_idx = signals[-1]
    first = signal_idx - 1
    if side == "buy":
        initial_stop = min(float(df["Low"].iloc[first]), float(df["Low"].iloc[signal_idx]))
    else:
        initial_stop = max(float(df["High"].iloc[first]), float(df["High"].iloc[signal_idx]))
    return _rolling_trigger_state(df, ema9, signal_idx, side, name, initial_stop=initial_stop)


def _ifr2_stormer_state(df: pd.DataFrame, rsi2: pd.Series) -> dict:
    name = "IFR2 Stormer clássico"
    if len(df) < 2 or not _finite(rsi2.iloc[-1]):
        return _base_state(passed=False, name=name, status="sem dados suficientes")
    value = float(rsi2.iloc[-1])
    if value >= 5:
        return _base_state(passed=False, name=name, status=f"IFR2 em {value:.2f}; precisa estar abaixo de 5")

    high = float(df["High"].iloc[-1])
    low = float(df["Low"].iloc[-1])
    close = float(df["Close"].iloc[-1])
    stop = low - 0.30 * (high - low)
    return _base_state(
        passed=True,
        name=name,
        status=f"IFR2 em {value:.2f}; entrada clássica no fechamento",
        direction="Compra",
        signal_date=df.index[-1],
        trigger_date=df.index[-1],
        entry=close,
        stop=stop,
    )


def _inside_bar_state(df: pd.DataFrame) -> dict:
    name = "Inside Bar"
    if len(df) < 2:
        return _base_state(passed=False, name=name, status="sem dados suficientes")
    inside = (
        float(df["High"].iloc[-1]) < float(df["High"].iloc[-2])
        and float(df["Low"].iloc[-1]) > float(df["Low"].iloc[-2])
    )
    return _base_state(
        passed=inside,
        name=name,
        status="Inside Bar formado" if inside else "candle atual não é Inside Bar",
        signal_date=df.index[-1] if inside else None,
        trigger_date=df.index[-1] if inside else None,
    )


def special_setup_state(df: pd.DataFrame, op: str, left: pd.Series) -> dict:
    if op == "pfr_buy":
        return _pfr_state(df, "buy")
    if op == "pfr_sell":
        return _pfr_state(df, "sell")
    if op == "setup_123_buy":
        return _setup_123_state(df, "buy")
    if op == "setup_123_sell":
        return _setup_123_state(df, "sell")
    if op == "setup_92_buy":
        return _setup_92_state(df, left, "buy")
    if op == "setup_92_sell":
        return _setup_92_state(df, left, "sell")
    if op == "setup_93_buy":
        return _setup_93_state(df, left, "buy")
    if op == "setup_93_sell":
        return _setup_93_state(df, left, "sell")
    if op == "ifr2_stormer":
        return _ifr2_stormer_state(df, left)
    if op == "inside_bar":
        return _inside_bar_state(df)
    raise ValueError(f"Setup especial não suportado: {op}")


def special_setup_description(op: str) -> str:
    return SPECIAL_SETUP_DESCRIPTIONS.get(op, op)


def evaluate_context_filter(df: pd.DataFrame, name: str) -> tuple[bool, str]:
    close = df["Close"].astype(float)

    if name == "Inside Bar atual":
        if len(df) < 2:
            return False, "Inside Bar: sem dados suficientes"
        passed = float(df["High"].iloc[-1]) < float(df["High"].iloc[-2]) and float(df["Low"].iloc[-1]) > float(df["Low"].iloc[-2])
        return bool(passed), "Inside Bar atual"

    if name in {"Éden dos Traders — Compra", "Éden dos Traders — Venda"}:
        e8 = ema(close, 8)
        e80 = ema(close, 80)
        if len(df) < 2 or not all(_finite(v) for v in [e8.iloc[-1], e8.iloc[-2], e80.iloc[-1], e80.iloc[-2]]):
            return False, f"{name}: sem dados suficientes"
        if name.endswith("Compra"):
            passed = e8.iloc[-1] > e80.iloc[-1] and e8.iloc[-1] > e8.iloc[-2] and e80.iloc[-1] > e80.iloc[-2]
        else:
            passed = e8.iloc[-1] < e80.iloc[-1] and e8.iloc[-1] < e8.iloc[-2] and e80.iloc[-1] < e80.iloc[-2]
        return bool(passed), name

    if name in {"MME80 ascendente", "MME80 descendente"}:
        e80 = ema(close, 80)
        if len(df) < 2 or not (_finite(e80.iloc[-1]) and _finite(e80.iloc[-2])):
            return False, f"{name}: sem dados suficientes"
        passed = e80.iloc[-1] > e80.iloc[-2] if name.endswith("ascendente") else e80.iloc[-1] < e80.iloc[-2]
        return bool(passed), name

    if name in {"Stormer MME49 — Compra", "Stormer MME49 — Venda"}:
        e49 = ema(close, 49)
        if len(df) < 2 or not (_finite(e49.iloc[-1]) and _finite(e49.iloc[-2])):
            return False, f"{name}: sem dados suficientes"
        if name.endswith("Compra"):
            passed = close.iloc[-1] > e49.iloc[-1] and e49.iloc[-1] > e49.iloc[-2]
        else:
            passed = close.iloc[-1] < e49.iloc[-1] and e49.iloc[-1] < e49.iloc[-2]
        return bool(passed), name

    if name in {"Preço acima da MME200", "Preço abaixo da MME200"}:
        e200 = ema(close, 200)
        if not _finite(e200.iloc[-1]):
            return False, f"{name}: sem dados suficientes"
        passed = close.iloc[-1] > e200.iloc[-1] if "acima" in name else close.iloc[-1] < e200.iloc[-1]
        return bool(passed), name

    return False, f"Filtro desconhecido: {name}"


def evaluate_context_filters(df: pd.DataFrame, filters: list[str] | None) -> tuple[bool, list[str]]:
    if not filters:
        return True, []
    details = []
    checks = []
    for name in filters:
        passed, label = evaluate_context_filter(df, name)
        checks.append(bool(passed))
        details.append(f"{'✓' if passed else '✗'} {label}")
    return all(checks), details


def describe_context_filters(filters: list[str] | None) -> str:
    if not filters:
        return "Nenhum"
    return " AND ".join(filters)
