from __future__ import annotations

import pandas as pd

from indicators import ema, sma


SETUP_ID = "landry_adjusted_buy"
ENTRY_OFFSET = 0.01
STOP_OFFSET = 0.05


def _finite(value) -> bool:
    try:
        return not pd.isna(value)
    except Exception:
        return False


def _trend_up(sma10: pd.Series, ema20: pd.Series, ema30: pd.Series, i: int) -> bool:
    if i < 1:
        return False
    values = [
        sma10.iloc[i], sma10.iloc[i - 1],
        ema20.iloc[i], ema20.iloc[i - 1],
        ema30.iloc[i], ema30.iloc[i - 1],
    ]
    if not all(_finite(v) for v in values):
        return False
    return bool(
        sma10.iloc[i] > sma10.iloc[i - 1]
        and ema20.iloc[i] > ema20.iloc[i - 1]
        and ema30.iloc[i] > ema30.iloc[i - 1]
    )


def _signal(df: pd.DataFrame, sma10: pd.Series, ema20: pd.Series, ema30: pd.Series, i: int) -> bool:
    if i < 2 or not _trend_up(sma10, ema20, ema30, i):
        return False
    current_low = float(df["Low"].iloc[i])
    previous_two_min = float(df["Low"].iloc[i - 2:i].astype(float).min())
    return current_low < previous_two_min


def compile_landry_adjusted_orders(df: pd.DataFrame) -> pd.DataFrame:
    """Compile o Dave Landry ajustado de compra em ordens válidas por 1 candle.

    Regras:
    - MMA10, MME20 e MME30 apontando para cima no candle-sinal;
    - mínima do candle-sinal menor que as mínimas dos 2 candles anteriores;
    - entrada = máxima do candle-sinal + R$ 0,01;
    - stop inicial = mínima do candle-sinal - R$ 0,05;
    - a ordem só existe no candle imediatamente seguinte. Se não houver rompimento,
      ela expira e o compilador volta a procurar um novo candle-sinal.
    """
    columns = [
        "ActiveDate", "OrderId", "Setup", "Side", "SignalDate",
        "TriggerPrice", "StopPrice", "CancelBelow", "CancelAbove",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    df = df.copy().sort_index()
    close = df["Close"].astype(float)
    sma10 = sma(close, 10)
    ema20 = ema(close, 20)
    ema30 = ema(close, 30)

    rows: list[dict] = []
    seq = 0
    # Usa 30 barras de aquecimento para reduzir viés de inicialização da MME30.
    start = max(30, 2)
    for i in range(start, len(df) - 1):
        if not _signal(df, sma10, ema20, ema30, i):
            continue

        seq += 1
        rows.append(
            {
                "ActiveDate": df.index[i + 1],
                "OrderId": f"{SETUP_ID}:{seq}:{df.index[i]}",
                "Setup": SETUP_ID,
                "Side": "long",
                "SignalDate": df.index[i],
                "TriggerPrice": float(df["High"].iloc[i]) + ENTRY_OFFSET,
                "StopPrice": float(df["Low"].iloc[i]) - STOP_OFFSET,
                "CancelBelow": None,
                "CancelAbove": None,
            }
        )

    return pd.DataFrame(rows, columns=columns)
