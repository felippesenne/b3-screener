from __future__ import annotations

import math

import pandas as pd

from indicators import ema


TRADE_DE_VALOR_SETUP_OPS = {
    "setup_94_buy",
    "landry_buy",
    "landry_sell",
    "pivot_breakout_buy",
    "pivot_breakout_sell",
    "rapf_buy",
    "rapf_sell",
}

TRADE_DE_VALOR_SETUP_DESCRIPTIONS = {
    "setup_94_buy": (
        "Setup 9.4 — O Susto (Compra): em tendência de alta, a MME9 vira para baixo e, no candle seguinte, "
        "volta a apontar para cima sem perder a mínima do candle anterior; gatilho na máxima do candle de retomada. "
        "Formalização do screener: MME21 > MME50 e ambas ascendentes no contexto."
    ),
    "landry_buy": (
        "Dave Landry — Compra: MME21 ascendente e candle com mínima abaixo das duas mínimas anteriores; "
        "gatilho na máxima do candle-sinal e stop R$0,01 abaixo da mínima."
    ),
    "landry_sell": (
        "Dave Landry — Venda: MME21 descendente e candle com máxima acima das duas máximas anteriores; "
        "gatilho na mínima do candle-sinal e stop R$0,01 acima da máxima."
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
    "rapf_buy": (
        "RAPF Compra: correção perde MME9/MME21/MME50 no gráfico menor, enquanto o gráfico maior permanece em tendência de alta "
        "e toca/rejeita MME9 ou MME21; o setup arma quando MME9 e MME21 do gráfico menor voltam a subir. "
        "Gatilho na máxima do candle de retomada."
    ),
    "rapf_sell": (
        "RAPF Venda: repique supera MME9/MME21/MME50 no gráfico menor, enquanto o gráfico maior permanece em tendência de baixa "
        "e toca/rejeita MME9 ou MME21; o setup arma quando MME9 e MME21 do gráfico menor voltam a cair. "
        "Gatilho na mínima do candle de retomada."
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


def _setup_94_buy_signal(df: pd.DataFrame, i: int) -> bool:
    if i < 3:
        return False
    close = df["Close"].astype(float)
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)
    vals = [e9.iloc[i - 3], e9.iloc[i - 2], e9.iloc[i - 1], e9.iloc[i], e21.iloc[i - 1], e21.iloc[i], e50.iloc[i - 1], e50.iloc[i]]
    if not all(_finite(v) for v in vals):
        return False

    trend_up = (
        e21.iloc[i] > e50.iloc[i]
        and e21.iloc[i] > e21.iloc[i - 1]
        and e50.iloc[i] > e50.iloc[i - 1]
    )
    turned_down = e9.iloc[i - 2] > e9.iloc[i - 3] and e9.iloc[i - 1] < e9.iloc[i - 2]
    turned_back_up = e9.iloc[i] > e9.iloc[i - 1]
    did_not_lose_low = float(df["Low"].iloc[i]) >= float(df["Low"].iloc[i - 1])
    return bool(trend_up and turned_down and turned_back_up and did_not_lose_low)


def _setup_94_buy_state(df: pd.DataFrame) -> dict:
    name = "Setup 9.4 — O Susto Compra"
    if len(df) < 55:
        return _state(passed=False, name=name, status="sem dados suficientes", direction="Compra")

    last = len(df) - 1
    candidates = [i for i in (last, last - 1) if i >= 3 and _setup_94_buy_signal(df, i)]
    if not candidates:
        return _state(passed=False, name=name, status="sem O Susto recente", direction="Compra")
    signal_idx = max(candidates)
    stop = min(float(df["Low"].iloc[signal_idx - 1]), float(df["Low"].iloc[signal_idx]))
    return _signal_or_next_bar_state(
        df,
        signal_idx,
        "buy",
        name,
        stop,
        "Candle de retomada formado; aguardando rompimento da máxima",
    )


def _landry_signal(df: pd.DataFrame, i: int, side: str) -> bool:
    if i < 2:
        return False
    close = df["Close"].astype(float)
    e21 = ema(close, 21)
    if not (_finite(e21.iloc[i]) and _finite(e21.iloc[i - 1])):
        return False
    if side == "buy":
        return bool(
            e21.iloc[i] > e21.iloc[i - 1]
            and float(df["Low"].iloc[i]) < float(df["Low"].iloc[i - 2:i].min())
        )
    return bool(
        e21.iloc[i] < e21.iloc[i - 1]
        and float(df["High"].iloc[i]) > float(df["High"].iloc[i - 2:i].max())
    )


def _landry_state(df: pd.DataFrame, side: str) -> dict:
    name = "Dave Landry Compra" if side == "buy" else "Dave Landry Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 25:
        return _state(passed=False, name=name, status="sem dados suficientes", direction=direction)

    last = len(df) - 1
    candidates = [i for i in (last, last - 1) if i >= 2 and _landry_signal(df, i, side)]
    if not candidates:
        return _state(passed=False, name=name, status="sem sinal Landry recente", direction=direction)
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
        "Candle-sinal formado; aguardando rompimento",
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


def _resample_higher_timeframe(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) < 3:
        return pd.DataFrame()
    deltas = pd.Series(df.index).sort_values().diff().dt.days.dropna()
    median_days = float(deltas.median()) if not deltas.empty else 1.0
    if median_days <= 3:
        rule = "W-FRI"
    elif median_days <= 10:
        rule = "ME"
    else:
        rule = "QE"

    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    return df.resample(rule).agg(agg).dropna(subset=["Close"])


def _higher_touch_ok(higher: pd.DataFrame, side: str) -> tuple[bool, str]:
    if len(higher) < 24:
        return False, "gráfico maior sem histórico suficiente"
    close = higher["Close"].astype(float)
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    if not all(_finite(v) for v in [e9.iloc[-1], e9.iloc[-2], e21.iloc[-1], e21.iloc[-2]]):
        return False, "gráfico maior sem médias suficientes"

    if side == "buy":
        trend = e9.iloc[-1] > e9.iloc[-2] and e21.iloc[-1] > e21.iloc[-2]
        distances = []
        for j in range(max(0, len(higher) - 2), len(higher)):
            low = float(higher["Low"].iloc[j])
            for series in (e9, e21):
                if _finite(series.iloc[j]) and float(series.iloc[j]) != 0:
                    distances.append(abs(low - float(series.iloc[j])) / abs(float(series.iloc[j])))
    else:
        trend = e9.iloc[-1] < e9.iloc[-2] and e21.iloc[-1] < e21.iloc[-2]
        distances = []
        for j in range(max(0, len(higher) - 2), len(higher)):
            high = float(higher["High"].iloc[j])
            for series in (e9, e21):
                if _finite(series.iloc[j]) and float(series.iloc[j]) != 0:
                    distances.append(abs(high - float(series.iloc[j])) / abs(float(series.iloc[j])))

    touched = bool(distances and min(distances) <= 0.03)
    return bool(trend and touched), f"gráfico maior {'em alta' if side == 'buy' else 'em baixa'} com toque em MME9/MME21"


def _rapf_state(df: pd.DataFrame, side: str) -> dict:
    name = "RAPF Compra" if side == "buy" else "RAPF Venda"
    direction = "Compra" if side == "buy" else "Venda"
    if len(df) < 55:
        return _state(passed=False, name=name, status="sem dados suficientes no gráfico menor", direction=direction)

    higher = _resample_higher_timeframe(df)
    higher_ok, higher_label = _higher_touch_ok(higher, side)
    if not higher_ok:
        return _state(passed=False, name=name, status=higher_label, direction=direction)

    close = df["Close"].astype(float)
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)
    last = len(df) - 1
    vals = [e9.iloc[-1], e9.iloc[-2], e21.iloc[-1], e21.iloc[-2], e50.iloc[-1]]
    if not all(_finite(v) for v in vals):
        return _state(passed=False, name=name, status="sem médias suficientes no gráfico menor", direction=direction)

    correction_found = False
    start = max(0, last - 10)
    for j in range(start, last):
        if not all(_finite(v) for v in [e9.iloc[j], e21.iloc[j], e50.iloc[j]]):
            continue
        c = float(close.iloc[j])
        if side == "buy" and c < e9.iloc[j] and c < e21.iloc[j] and c < e50.iloc[j]:
            correction_found = True
            break
        if side == "sell" and c > e9.iloc[j] and c > e21.iloc[j] and c > e50.iloc[j]:
            correction_found = True
            break

    if not correction_found:
        return _state(passed=False, name=name, status="gráfico menor não perdeu as três médias recentemente", direction=direction)

    if side == "buy":
        retake = (
            e9.iloc[-1] > e9.iloc[-2]
            and e21.iloc[-1] > e21.iloc[-2]
            and float(close.iloc[-1]) > float(e9.iloc[-1])
            and float(df["Close"].iloc[-1]) > float(df["Open"].iloc[-1])
        )
        entry = float(df["High"].iloc[-1])
        stop = float(df["Low"].iloc[max(0, last - 2):last + 1].min())
    else:
        retake = (
            e9.iloc[-1] < e9.iloc[-2]
            and e21.iloc[-1] < e21.iloc[-2]
            and float(close.iloc[-1]) < float(e9.iloc[-1])
            and float(df["Close"].iloc[-1]) < float(df["Open"].iloc[-1])
        )
        entry = float(df["Low"].iloc[-1])
        stop = float(df["High"].iloc[max(0, last - 2):last + 1].max())

    if not retake:
        return _state(passed=False, name=name, status="médias do gráfico menor ainda não retomaram a direção", direction=direction)

    avg_volume = float(df["Volume"].iloc[max(0, last - 20):last].mean())
    avg_range = float((df["High"] - df["Low"]).iloc[max(0, last - 20):last].mean())
    vol_ratio = float(df["Volume"].iloc[-1]) / avg_volume if avg_volume > 0 else float("nan")
    range_ratio = float(df["High"].iloc[-1] - df["Low"].iloc[-1]) / avg_range if avg_range > 0 else float("nan")
    catalyst = ""
    if _finite(vol_ratio) and _finite(range_ratio):
        catalyst = f"; catalisadores: volume {vol_ratio:.1f}x, amplitude {range_ratio:.1f}x"

    return _state(
        passed=True,
        name=name,
        status=f"Retomada multitemporal armada{catalyst}",
        direction=direction,
        signal_date=df.index[-1],
        trigger_date=df.index[-1],
        entry=entry,
        stop=stop,
    )


def trade_de_valor_setup_state(df: pd.DataFrame, op: str) -> dict:
    if op == "setup_94_buy":
        return _setup_94_buy_state(df)
    if op == "landry_buy":
        return _landry_state(df, "buy")
    if op == "landry_sell":
        return _landry_state(df, "sell")
    if op == "pivot_breakout_buy":
        return _pivot_state(df, "buy")
    if op == "pivot_breakout_sell":
        return _pivot_state(df, "sell")
    if op == "rapf_buy":
        return _rapf_state(df, "buy")
    if op == "rapf_sell":
        return _rapf_state(df, "sell")
    raise ValueError(f"Setup Trade de Valor não suportado: {op}")


def trade_de_valor_setup_description(op: str) -> str:
    return TRADE_DE_VALOR_SETUP_DESCRIPTIONS.get(op, op)
