from __future__ import annotations

import pandas as pd

from indicators import ema, sma


SUPPORTED_SETUPS = {
    "setup_91_buy",
    "setup_91_sell",
    "pfr_buy",
    "pfr_sell",
    "setup_123_buy",
    "setup_123_sell",
    "landry_simple_buy",
    "landry_simple_sell",
    "bowtie_buy",
    "bowtie_sell",
}


def _finite(value) -> bool:
    try:
        return not pd.isna(value)
    except Exception:
        return False


def _row(
    *,
    df: pd.DataFrame,
    active_idx: int,
    order_id: str,
    setup: str,
    side: str,
    signal_idx: int,
    trigger: float,
    stop: float | None,
    cancel_below: float | None = None,
    cancel_above: float | None = None,
) -> dict:
    return {
        "ActiveDate": df.index[active_idx],
        "OrderId": order_id,
        "Setup": setup,
        "Side": side,
        "SignalDate": df.index[signal_idx],
        "TriggerPrice": float(trigger),
        "StopPrice": None if stop is None else float(stop),
        "CancelBelow": None if cancel_below is None else float(cancel_below),
        "CancelAbove": None if cancel_above is None else float(cancel_above),
    }


def _triggered(df: pd.DataFrame, idx: int, side: str, trigger: float) -> bool:
    if side == "long":
        return float(df["Open"].iloc[idx]) >= trigger or float(df["High"].iloc[idx]) >= trigger
    return float(df["Open"].iloc[idx]) <= trigger or float(df["Low"].iloc[idx]) <= trigger


def _compile_91(df: pd.DataFrame, side: str, tick_size: float) -> list[dict]:
    ema9 = ema(df["Close"].astype(float), 9)
    rows: list[dict] = []
    seq = 0

    for i in range(2, len(df) - 1):
        a, b, c = ema9.iloc[i - 2], ema9.iloc[i - 1], ema9.iloc[i]
        if not all(_finite(v) for v in (a, b, c)):
            continue

        turned = (b < a and c > b) if side == "long" else (b > a and c < b)
        if not turned:
            continue

        seq += 1
        setup = "setup_91_buy" if side == "long" else "setup_91_sell"
        order_id = f"{setup}:{seq}:{df.index[i]}"
        trigger = float(df["High"].iloc[i]) + tick_size if side == "long" else float(df["Low"].iloc[i]) - tick_size
        stop = float(df["Low"].iloc[i]) - tick_size if side == "long" else float(df["High"].iloc[i]) + tick_size

        for j in range(i + 1, len(df)):
            rows.append(
                _row(
                    df=df,
                    active_idx=j,
                    order_id=order_id,
                    setup=setup,
                    side=side,
                    signal_idx=i,
                    trigger=trigger,
                    stop=stop,
                )
            )
            if _triggered(df, j, side, trigger):
                break

            prev, now = ema9.iloc[j - 1], ema9.iloc[j]
            if not (_finite(prev) and _finite(now)):
                break
            still_valid = now > prev if side == "long" else now < prev
            if not still_valid:
                break

    return rows


def _pfr_signal(df: pd.DataFrame, i: int, side: str) -> bool:
    if i < 2:
        return False
    if side == "long":
        return (
            float(df["Low"].iloc[i]) < float(df["Low"].iloc[i - 2:i].min())
            and float(df["Close"].iloc[i]) > float(df["Close"].iloc[i - 1])
        )
    return (
        float(df["High"].iloc[i]) > float(df["High"].iloc[i - 2:i].max())
        and float(df["Close"].iloc[i]) < float(df["Close"].iloc[i - 1])
    )


def _setup_123_signal(df: pd.DataFrame, i: int, side: str) -> bool:
    if i < 2:
        return False
    c1, c2, c3 = i - 2, i - 1, i
    if side == "long":
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


def _compile_one_bar_patterns(df: pd.DataFrame, setup: str, side: str, tick_size: float) -> list[dict]:
    rows: list[dict] = []
    seq = 0
    for i in range(2, len(df) - 1):
        if setup.startswith("pfr_"):
            matched = _pfr_signal(df, i, side)
            stop_idx = i
        elif setup.startswith("setup_123_"):
            matched = _setup_123_signal(df, i, side)
            stop_idx = i - 1
        else:
            raise ValueError(setup)

        if not matched:
            continue
        seq += 1
        j = i + 1
        if side == "long":
            trigger = float(df["High"].iloc[i]) + tick_size
            stop = float(df["Low"].iloc[stop_idx]) - tick_size
        else:
            trigger = float(df["Low"].iloc[i]) - tick_size
            stop = float(df["High"].iloc[stop_idx]) + tick_size
        rows.append(
            _row(
                df=df,
                active_idx=j,
                order_id=f"{setup}:{seq}:{df.index[i]}",
                setup=setup,
                side=side,
                signal_idx=i,
                trigger=trigger,
                stop=stop,
            )
        )
    return rows


def _landry_signal(df: pd.DataFrame, i: int, side: str) -> bool:
    if i < 2:
        return False
    if side == "long":
        return float(df["Low"].iloc[i]) < float(df["Low"].iloc[i - 2:i].min())
    return float(df["High"].iloc[i]) > float(df["High"].iloc[i - 2:i].max())


def _compile_landry(
    df: pd.DataFrame,
    setup: str,
    side: str,
    tick_size: float,
    valid_bars: int,
) -> list[dict]:
    rows: list[dict] = []
    seq = 0
    if valid_bars < 1:
        raise ValueError("landry_valid_bars deve ser >= 1.")

    for i in range(2, len(df) - 1):
        if not _landry_signal(df, i, side):
            continue
        seq += 1
        order_id = f"{setup}:{seq}:{df.index[i]}"
        if side == "long":
            trigger = float(df["High"].iloc[i]) + tick_size
            stop = float(df["Low"].iloc[i]) - tick_size
        else:
            trigger = float(df["Low"].iloc[i]) - tick_size
            stop = float(df["High"].iloc[i]) + tick_size

        for j in range(i + 1, min(len(df), i + 1 + valid_bars)):
            rows.append(
                _row(
                    df=df,
                    active_idx=j,
                    order_id=order_id,
                    setup=setup,
                    side=side,
                    signal_idx=i,
                    trigger=trigger,
                    stop=stop,
                )
            )
            if _triggered(df, j, side, trigger):
                break

    return rows


def _bowtie_formations(df: pd.DataFrame, side: str, transition_bars: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    if transition_bars < 1:
        raise ValueError("bowtie_transition_bars deve ser >= 1.")
    sma10 = sma(df["Close"].astype(float), 10)
    ema20 = ema(df["Close"].astype(float), 20)
    ema30 = ema(df["Close"].astype(float), 30)
    up = (sma10 > ema20) & (ema20 > ema30)
    down = (sma10 < ema20) & (ema20 < ema30)
    target = up if side == "long" else down
    opposite = down if side == "long" else up

    formation = pd.Series(False, index=df.index, dtype=bool)
    for i in range(1, len(df)):
        if not bool(target.iloc[i]) or bool(target.iloc[i - 1]):
            continue
        start = max(0, i - transition_bars)
        if bool(opposite.iloc[start:i].any()):
            formation.iloc[i] = True
    return formation, ema20, target


def _compile_bowtie(
    df: pd.DataFrame,
    setup: str,
    side: str,
    tick_size: float,
    transition_bars: int,
) -> list[dict]:
    rows: list[dict] = []
    formation, ema20, proper_order = _bowtie_formations(df, side, transition_bars)
    seq = 0

    for formed_idx in [i for i, value in enumerate(formation) if bool(value)]:
        pullback_idx = None
        for j in range(formed_idx + 1, len(df) - 1):
            if not bool(proper_order.iloc[j]):
                break
            pullback = (
                float(df["Low"].iloc[j]) < float(df["Low"].iloc[j - 1])
                if side == "long"
                else float(df["High"].iloc[j]) > float(df["High"].iloc[j - 1])
            )
            if not pullback:
                continue
            if side == "long" and float(df["Low"].iloc[j]) < float(ema20.iloc[j]):
                break
            if side == "short" and float(df["High"].iloc[j]) > float(ema20.iloc[j]):
                break
            pullback_idx = j
            break

        if pullback_idx is None:
            continue

        seq += 1
        order_id = f"{setup}:{seq}:{df.index[pullback_idx]}"
        for active_idx in range(pullback_idx + 1, len(df)):
            prior = active_idx - 1
            if side == "long":
                trigger = float(df["High"].iloc[prior]) + tick_size
                stop = float(df["Low"].iloc[pullback_idx:active_idx].min()) - tick_size
                cancel_below = float(ema20.iloc[prior])
                cancel_above = None
            else:
                trigger = float(df["Low"].iloc[prior]) - tick_size
                stop = float(df["High"].iloc[pullback_idx:active_idx].max()) + tick_size
                cancel_below = None
                cancel_above = float(ema20.iloc[prior])

            rows.append(
                _row(
                    df=df,
                    active_idx=active_idx,
                    order_id=order_id,
                    setup=setup,
                    side=side,
                    signal_idx=pullback_idx,
                    trigger=trigger,
                    stop=stop,
                    cancel_below=cancel_below,
                    cancel_above=cancel_above,
                )
            )

            open_px = float(df["Open"].iloc[active_idx])
            high_px = float(df["High"].iloc[active_idx])
            low_px = float(df["Low"].iloc[active_idx])
            if side == "long":
                cancelled = open_px < cancel_below or low_px < cancel_below
                triggered = open_px >= trigger or high_px >= trigger
            else:
                cancelled = open_px > cancel_above or high_px > cancel_above
                triggered = open_px <= trigger or low_px <= trigger
            if cancelled or triggered:
                break

    return rows


def compile_setup_orders(
    df: pd.DataFrame,
    setup: str,
    *,
    tick_size: float = 0.01,
    landry_valid_bars: int = 1,
    bowtie_transition_bars: int = 4,
) -> pd.DataFrame:
    """Compile classic setup semantics into dated stop-entry order instructions."""
    if setup not in SUPPORTED_SETUPS:
        raise ValueError(f"Setup não suportado: {setup}")
    if tick_size < 0:
        raise ValueError("tick_size não pode ser negativo.")
    if df.empty:
        return pd.DataFrame(
            columns=[
                "ActiveDate", "OrderId", "Setup", "Side", "SignalDate",
                "TriggerPrice", "StopPrice", "CancelBelow", "CancelAbove",
            ]
        )

    df = df.copy().sort_index()
    side = "long" if setup.endswith("_buy") else "short"

    if setup.startswith("setup_91_"):
        rows = _compile_91(df, side, tick_size)
    elif setup.startswith("pfr_") or setup.startswith("setup_123_"):
        rows = _compile_one_bar_patterns(df, setup, side, tick_size)
    elif setup.startswith("landry_simple_"):
        rows = _compile_landry(df, setup, side, tick_size, landry_valid_bars)
    elif setup.startswith("bowtie_"):
        rows = _compile_bowtie(df, setup, side, tick_size, bowtie_transition_bars)
    else:
        rows = []

    return pd.DataFrame(rows)
