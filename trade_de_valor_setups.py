from __future__ import annotations

import math

import pandas as pd

from indicators import ema


# Mantemos expostos somente os setups que permanecem no menu curado.
TRADE_DE_VALOR_SETUP_OPS = {
    "landry_buy",
    "landry_sell",
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
    """Landry objetivo: tendência da MME21 + extremo de 3 barras + proximidade da MME21.

    A proximidade aceita candle cujo range intercepte uma faixa de +/-1% ao redor da MME21.
    Isso evita marcar extremos distantes da média como se fossem o pullback do setup.
    """
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
    if side == "buy":
        stop = float(df["Low"].iloc[signal_idx]) - 0.01
    else:
        stop = float(df["High"].iloc[signal_idx]) + 0.01

    return _signal_or_next_bar_state(
        df,
        signal_idx,
        side,
        name,
        stop,
        "Candle-sinal formado próximo da MME21; aguardando rompimento",
    )


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
    if op == "pivot_breakout_buy":
        return _pivot_state(df, "buy")
    if op == "pivot_breakout_sell":
        return _pivot_state(df, "sell")
    raise ValueError(f"Setup Trade de Valor não suportado: {op}")


def trade_de_valor_setup_description(op: str) -> str:
    return TRADE_DE_VALOR_SETUP_DESCRIPTIONS.get(op, op)
