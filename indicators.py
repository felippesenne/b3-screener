import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi_wilder(series: pd.Series, period: int = 2) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100)
    rsi = rsi.where(avg_gain != 0, 0)
    return rsi


def resample_ohlcv(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "Diário":
        return df.copy()

    rule = {
        "Semanal": "W-FRI",
        "Mensal": "ME",
    }[timeframe]

    out = df.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    })

    return out.dropna(subset=["Close"])


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["IFR2"] = rsi_wilder(out["Close"], 2)
    out["MME9"] = ema(out["Close"], 9)
    out["MME50"] = ema(out["Close"], 50)
    out["MME80"] = ema(out["Close"], 80)
    out["MME200"] = ema(out["Close"], 200)

    for p in [9, 50, 80, 200]:
        out[f"MME{p}_UP"] = out[f"MME{p}"] > out[f"MME{p}"].shift(1)

    out["PRICE_ABOVE_MME200"] = out["Close"] > out["MME200"]
    return out
