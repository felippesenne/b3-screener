from __future__ import annotations

import json
from functools import lru_cache

import exchange_calendars as xcals
import numpy as np
import pandas as pd


# Primeira sessão disponível no calendário BVMF do exchange_calendars.
# Usar uma âncora fixa evita que os candles 2D/3D mudem de alinhamento quando
# o usuário troca o tamanho do histórico solicitado ao Yahoo Finance.
BVMF_MULTI_DAY_ANCHOR = pd.Timestamp("2006-09-26")


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi_wilder(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100)
    rsi = rsi.where(avg_gain != 0, 0)
    return rsi


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx_components(df: pd.DataFrame, period: int = 14):
    up_move = df["High"].diff()
    down_move = -df["Low"].diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_series = atr(df, period)
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_series
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_series
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx, plus_di, minus_di


@lru_cache(maxsize=8)
def _bvmf_session_ordinals(end_year: int) -> dict[pd.Timestamp, int]:
    """Mapeia cada pregão B3 para um ordinal estável desde a âncora fixa."""
    calendar = xcals.get_calendar(
        "BVMF",
        start=BVMF_MULTI_DAY_ANCHOR.strftime("%Y-%m-%d"),
        end=f"{end_year + 1}-12-31",
    )
    sessions = calendar.sessions_in_range(BVMF_MULTI_DAY_ANCHOR, calendar.last_session)
    return {pd.Timestamp(session).tz_localize(None): idx for idx, session in enumerate(sessions)}


def _normalized_session_index(index: pd.Index) -> pd.DatetimeIndex:
    sessions = pd.DatetimeIndex(index)
    if sessions.tz is not None:
        sessions = sessions.tz_convert("America/Sao_Paulo").tz_localize(None)
    return sessions.normalize()


def _resample_trading_sessions(df: pd.DataFrame, sessions_per_bar: int) -> pd.DataFrame:
    """Agrega OHLCV por quantidade de pregões B3, nunca por dias corridos.

    Os blocos são ancorados em uma sessão B3 fixa para permanecerem estáveis
    independentemente do período de histórico baixado. O último bloco parcial é
    preservado, reproduzindo o candle corrente ainda em formação.
    """
    if df.empty:
        return df.copy()
    if sessions_per_bar < 2:
        raise ValueError("sessions_per_bar deve ser >= 2")

    session_dates = _normalized_session_index(df.index)
    ordinals = _bvmf_session_ordinals(int(session_dates.max().year))

    session_numbers = []
    missing = []
    for session in session_dates:
        number = ordinals.get(session)
        if number is None:
            missing.append(session.strftime("%Y-%m-%d"))
        session_numbers.append(number)

    if missing:
        raise ValueError(
            "Datas fora do calendário B3 ao montar timeframe multi-dia: " + ", ".join(missing[:5])
        )

    work = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    work["_session_date"] = session_dates.to_numpy()
    work["_block"] = [int(number) // sessions_per_bar for number in session_numbers]

    out = work.groupby("_block", sort=True).agg(
        {
            "Open": "first",
            "High": "max",
            "Low": "min",
            "Close": "last",
            "Volume": "sum",
            "_session_date": "max",
        }
    )
    out = out.set_index("_session_date")
    out.index.name = df.index.name
    return out[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "Diário":
        return df.copy()
    if timeframe == "2 dias":
        return _resample_trading_sessions(df, 2)
    if timeframe == "3 dias":
        return _resample_trading_sessions(df, 3)
    rule = {"Semanal": "W-FRI", "Mensal": "ME"}[timeframe]
    out = df.resample(rule).agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return out.dropna(subset=["Close"])


def spec_key(spec: dict) -> str:
    return json.dumps(spec, sort_keys=True, ensure_ascii=False)


def indicator_label(spec: dict) -> str:
    kind = spec["kind"]
    if kind == "PRICE":
        return spec.get("field", "Close")
    if kind in {"RSI", "EMA", "SMA", "ATR"}:
        names = {"RSI": "IFR", "EMA": "MME", "SMA": "MMS", "ATR": "ATR"}
        return f"{names[kind]}({spec['period']})"
    if kind == "MACD":
        output = {"macd": "MACD", "signal": "Sinal", "hist": "Histograma"}[spec["output"]]
        return f"MACD({spec['fast']},{spec['slow']},{spec['signal']}) {output}"
    if kind == "BB":
        output = {
            "middle": "Média",
            "upper": "Superior",
            "lower": "Inferior",
            "pctb": "%B",
            "bandwidth": "Bandwidth",
        }[spec["output"]]
        return f"Bollinger({spec['period']},{spec['std']}) {output}"
    if kind == "STOCH":
        output = {"k": "%K", "d": "%D"}[spec["output"]]
        return f"Estocástico({spec['k_period']},{spec['smooth_k']},{spec['d_period']}) {output}"
    if kind == "ADX":
        output = {"adx": "ADX", "plus_di": "+DI", "minus_di": "-DI"}[spec["output"]]
        return f"ADX({spec['period']}) {output}"
    if kind == "VOLUME":
        output = {"volume": "Volume", "average": "Média", "ratio": "Razão"}[spec["output"]]
        return f"{output} Volume({spec.get('period', 20)})"
    return kind


def indicator_series(df: pd.DataFrame, spec: dict) -> pd.Series:
    kind = spec["kind"]

    if kind == "PRICE":
        return df[spec.get("field", "Close")].astype(float)
    if kind == "RSI":
        return rsi_wilder(df["Close"], int(spec["period"]))
    if kind == "EMA":
        return ema(df["Close"], int(spec["period"]))
    if kind == "SMA":
        return sma(df["Close"], int(spec["period"]))
    if kind == "ATR":
        return atr(df, int(spec["period"]))

    if kind == "MACD":
        fast = ema(df["Close"], int(spec["fast"]))
        slow = ema(df["Close"], int(spec["slow"]))
        macd_line = fast - slow
        signal_line = ema(macd_line, int(spec["signal"]))
        values = {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}
        return values[spec["output"]]

    if kind == "BB":
        period = int(spec["period"])
        mult = float(spec["std"])
        middle = sma(df["Close"], period)
        std = df["Close"].rolling(period, min_periods=period).std(ddof=0)
        upper = middle + mult * std
        lower = middle - mult * std
        width = (upper - lower).replace(0, np.nan)
        values = {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "pctb": (df["Close"] - lower) / width,
            "bandwidth": width / middle.replace(0, np.nan),
        }
        return values[spec["output"]]

    if kind == "STOCH":
        k_period = int(spec["k_period"])
        smooth_k = int(spec["smooth_k"])
        d_period = int(spec["d_period"])
        low = df["Low"].rolling(k_period, min_periods=k_period).min()
        high = df["High"].rolling(k_period, min_periods=k_period).max()
        raw_k = 100 * (df["Close"] - low) / (high - low).replace(0, np.nan)
        k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean()
        d = k.rolling(d_period, min_periods=d_period).mean()
        return {"k": k, "d": d}[spec["output"]]

    if kind == "ADX":
        adx, plus_di, minus_di = adx_components(df, int(spec["period"]))
        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}[spec["output"]]

    if kind == "VOLUME":
        period = int(spec.get("period", 20))
        avg = sma(df["Volume"].astype(float), period)
        values = {
            "volume": df["Volume"].astype(float),
            "average": avg,
            "ratio": df["Volume"].astype(float) / avg.replace(0, np.nan),
        }
        return values[spec["output"]]

    raise ValueError(f"Indicador não suportado: {kind}")


def build_series_cache(df: pd.DataFrame, specs: list[dict]) -> dict[str, pd.Series]:
    cache = {}
    for spec in specs:
        key = spec_key(spec)
        if key not in cache:
            cache[key] = indicator_series(df, spec)
    return cache
