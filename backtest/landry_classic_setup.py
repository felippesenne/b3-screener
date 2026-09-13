from __future__ import annotations

import pandas as pd

from indicators import ema


def _classic_trend_anchor(
    df: pd.DataFrame,
    ema20: pd.Series,
    ema50: pd.Series,
    anchor: int,
    side: str,
    trend_lookback: int,
) -> bool:
    if anchor < max(50, trend_lookback - 1, 3):
        return False
    values = [ema20.iloc[anchor], ema50.iloc[anchor], ema20.iloc[anchor - 3], ema50.iloc[anchor - 3]]
    if any(pd.isna(v) for v in values):
        return False

    close = float(df["Close"].iloc[anchor])
    if side == "long":
        recent_extreme = float(df["High"].iloc[anchor - trend_lookback + 1 : anchor + 1].max())
        return (
            close > float(ema20.iloc[anchor]) > float(ema50.iloc[anchor])
            and float(ema20.iloc[anchor]) > float(ema20.iloc[anchor - 3])
            and float(ema50.iloc[anchor]) > float(ema50.iloc[anchor - 3])
            and float(df["High"].iloc[anchor]) >= recent_extreme
        )

    recent_extreme = float(df["Low"].iloc[anchor - trend_lookback + 1 : anchor + 1].min())
    return (
        close < float(ema20.iloc[anchor]) < float(ema50.iloc[anchor])
        and float(ema20.iloc[anchor]) < float(ema20.iloc[anchor - 3])
        and float(ema50.iloc[anchor]) < float(ema50.iloc[anchor - 3])
        and float(df["Low"].iloc[anchor]) <= recent_extreme
    )


def _pullback_continues(df: pd.DataFrame, idx: int, side: str) -> bool:
    if side == "long":
        return float(df["High"].iloc[idx]) < float(df["High"].iloc[idx - 1])
    return float(df["Low"].iloc[idx]) > float(df["Low"].iloc[idx - 1])


def _triggered(df: pd.DataFrame, idx: int, side: str, trigger: float) -> bool:
    if side == "long":
        return float(df["Open"].iloc[idx]) >= trigger or float(df["High"].iloc[idx]) >= trigger
    return float(df["Open"].iloc[idx]) <= trigger or float(df["Low"].iloc[idx]) <= trigger


def _cancelled(df: pd.DataFrame, idx: int, side: str, stop: float) -> bool:
    if side == "long":
        return float(df["Open"].iloc[idx]) < stop or float(df["Low"].iloc[idx]) < stop
    return float(df["Open"].iloc[idx]) > stop or float(df["High"].iloc[idx]) > stop


def compile_landry_classic_orders(
    df: pd.DataFrame,
    setup: str,
    side: str,
    *,
    tick_size: float = 0.01,
    min_pullback_bars: int = 3,
    max_pullback_bars: int = 7,
    trend_lookback: int = 20,
) -> list[dict]:
    """Compile a deterministic Dave Landry Simple Pullback model.

    Model:
    - established trend: EMA20/EMA50 in proper order and both sloping in the
      trend direction;
    - the pre-pullback anchor is a new ``trend_lookback``-bar extreme;
    - long: 3-7 consecutive lower highs; short: 3-7 consecutive higher lows;
    - from bar 3 onward, the next bar receives a rolling stop-entry above/below
      the most recently completed pullback bar;
    - the technical stop follows the pullback extreme accumulated so far;
    - touching the invalidation level before an intrabar trigger cancels the
      setup under the engine's conservative sequencing policy.
    """
    if min_pullback_bars < 1:
        raise ValueError("landry_min_pullback_bars deve ser >= 1.")
    if max_pullback_bars < min_pullback_bars:
        raise ValueError("landry_max_pullback_bars deve ser >= landry_min_pullback_bars.")
    if trend_lookback < 5:
        raise ValueError("landry_trend_lookback deve ser >= 5.")

    close = df["Close"].astype(float)
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    rows: list[dict] = []
    seq = 0
    anchor = max(50, trend_lookback - 1, 3)

    while anchor < len(df) - 2:
        if not _classic_trend_anchor(df, ema20, ema50, anchor, side, trend_lookback):
            anchor += 1
            continue

        first = anchor + 1
        if not _pullback_continues(df, first, side):
            anchor += 1
            continue

        seq += 1
        order_id = f"{setup}:{seq}:{df.index[anchor]}"
        count = 0
        j = first
        last_seen = j

        while j < len(df) - 1 and count < max_pullback_bars and _pullback_continues(df, j, side):
            count += 1
            last_seen = j
            if count >= min_pullback_bars:
                active_idx = j + 1
                if side == "long":
                    trigger = float(df["High"].iloc[j]) + tick_size
                    stop = float(df["Low"].iloc[first : j + 1].min()) - tick_size
                    cancel_below = stop
                    cancel_above = None
                else:
                    trigger = float(df["Low"].iloc[j]) - tick_size
                    stop = float(df["High"].iloc[first : j + 1].max()) + tick_size
                    cancel_below = None
                    cancel_above = stop

                rows.append(
                    {
                        "ActiveDate": df.index[active_idx],
                        "OrderId": order_id,
                        "Setup": setup,
                        "Side": side,
                        "SignalDate": df.index[j],
                        "TriggerPrice": float(trigger),
                        "StopPrice": float(stop),
                        "CancelBelow": cancel_below,
                        "CancelAbove": cancel_above,
                    }
                )

                if _cancelled(df, active_idx, side, stop) or _triggered(df, active_idx, side, trigger):
                    last_seen = active_idx
                    break
            j += 1

        # Skip the bars already consumed by this pullback candidate. This avoids
        # counting the same correction as several overlapping formations.
        anchor = max(anchor + 1, last_seen + 1)

    return rows
