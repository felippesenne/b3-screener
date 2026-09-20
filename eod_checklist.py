from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from indicators import adx_components, atr, ema, resample_ohlcv, rsi_wilder
from scanner import _setup_91_state, classify_trend


@dataclass
class SetupCandidate:
    name: str
    strength: int
    status: str
    entry: float | None = None
    stop: float | None = None
    target: float | None = None


def _finite(value) -> bool:
    try:
        return not pd.isna(value) and math.isfinite(float(value))
    except Exception:
        return False


def _round(value, digits=2):
    if value is None or not _finite(value):
        return None
    return round(float(value), digits)


def _series_value(series: pd.Series, idx: int = -1):
    if series.empty:
        return None
    value = series.iloc[idx]
    return float(value) if _finite(value) else None


def _is_rising(series: pd.Series, bars: int = 3) -> bool:
    if len(series) <= bars:
        return False
    now = _series_value(series, -1)
    before = _series_value(series, -(bars + 1))
    return now is not None and before is not None and now > before


def _completed_resample(raw: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resample and conservatively remove a still-open weekly/monthly candle."""
    out = resample_ohlcv(raw, timeframe)
    if timeframe == "Diário" or out.empty or raw.empty:
        return out

    latest_raw = pd.Timestamp(raw.index.max()).normalize()
    latest_bucket = pd.Timestamp(out.index.max()).normalize()
    if latest_bucket > latest_raw:
        out = out.iloc[:-1]
    return out


def _trend_score(df: pd.DataFrame) -> tuple[float, str, dict]:
    close = df["Close"].astype(float)
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)
    e80 = ema(close, 80)
    e200 = ema(close, 200)

    values = {
        "close": _series_value(close),
        "e9": _series_value(e9),
        "e21": _series_value(e21),
        "e50": _series_value(e50),
        "e80": _series_value(e80),
        "e200": _series_value(e200),
    }
    if any(values[key] is None for key in ("close", "e21", "e50", "e80")):
        return 0.0, "Sem dados", values

    score = 0.0
    close_now = values["close"]
    e21_now, e50_now, e80_now, e200_now = values["e21"], values["e50"], values["e80"], values["e200"]

    base_up = _is_rising(e50, 3) and _is_rising(e80, 3)
    price_above_long = e200_now is not None and close_now > e200_now
    ordered = e21_now > e50_now > e80_now
    long_rising = e200_now is not None and _is_rising(e200, 3)

    if base_up and price_above_long:
        score += 1.0
    elif base_up or price_above_long:
        score += 0.5

    if ordered and long_rising:
        score += 1.0
    elif ordered or long_rising:
        score += 0.5

    score = min(2.0, score)

    if score >= 1.5:
        label = "Alta"
    elif score >= 0.75:
        label = "Alta moderada / transição"
    else:
        bearish_order = (
            e200_now is not None
            and close_now < e200_now
            and e21_now < e50_now < e80_now
            and not _is_rising(e50, 3)
        )
        label = "Baixa" if bearish_order else "Lateral / indefinida"

    return score, label, values


def _ifr2_state(df: pd.DataFrame) -> tuple[SetupCandidate | None, float | None]:
    rsi2 = rsi_wilder(df["Close"].astype(float), 2)
    current = _series_value(rsi2)
    if current is None:
        return None, None

    last = len(df) - 1
    lookback_start = max(0, last - 10)
    oversold = [
        i for i in range(lookback_start, last + 1)
        if _finite(rsi2.iloc[i]) and float(rsi2.iloc[i]) < 10
    ]

    if oversold:
        signal_idx = oversold[-1]
        trigger = float(df["High"].iloc[signal_idx])
        stop = float(df["Low"].iloc[signal_idx])
        triggered_idx = None

        for j in range(signal_idx + 1, last + 1):
            if float(df["High"].iloc[j]) > trigger:
                triggered_idx = j
                break
            trigger = min(trigger, float(df["High"].iloc[j]))
            stop = min(stop, float(df["Low"].iloc[j]))

        if triggered_idx is None:
            status = (
                f"IFR2 < 10; gatilho móvel em {trigger:.2f}"
                if signal_idx < last
                else f"IFR2 em {current:.1f}; candle de sinal formado"
            )
            return SetupCandidate(
                name="IFR2",
                strength=2,
                status=status,
                entry=trigger,
                stop=stop,
            ), current

        if triggered_idx == last:
            return SetupCandidate(
                name="IFR2",
                strength=2,
                status="Entrada acionada no último candle",
                entry=trigger,
                stop=stop,
            ), current

    if current < 25:
        return SetupCandidate(
            name="IFR2",
            strength=1,
            status=f"IFR2 em {current:.1f}; zona de atenção (<25)",
            entry=float(df["High"].iloc[-1]),
            stop=float(df["Low"].iloc[-1]),
        ), current

    return None, current


def _mean_reversion_state(df: pd.DataFrame, trend_score: float) -> tuple[SetupCandidate | None, float | None]:
    close = df["Close"].astype(float)
    e21 = ema(close, 21)
    atr14 = atr(df, 14)
    close_now = _series_value(close)
    mean_now = _series_value(e21)
    atr_now = _series_value(atr14)

    if close_now is None or mean_now is None or atr_now is None or atr_now <= 0:
        return None, None

    distance_atr = (close_now - mean_now) / atr_now
    if distance_atr <= -1.5 and trend_score >= 0.5:
        return SetupCandidate(
            name="Volta à média",
            strength=2,
            status=f"{abs(distance_atr):.2f} ATR abaixo da MME21",
            entry=float(df["High"].iloc[-1]),
            stop=float(df["Low"].iloc[-1]) - 0.25 * atr_now,
            target=mean_now,
        ), distance_atr

    if distance_atr <= -1.0:
        return SetupCandidate(
            name="Volta à média",
            strength=1,
            status=f"{abs(distance_atr):.2f} ATR abaixo da MME21; monitorar",
            entry=float(df["High"].iloc[-1]),
            stop=float(df["Low"].iloc[-1]) - 0.25 * atr_now,
            target=mean_now,
        ), distance_atr

    return None, distance_atr


def _classic_landry_anchor(
    df: pd.DataFrame,
    e20: pd.Series,
    e50: pd.Series,
    anchor: int,
    trend_lookback: int = 20,
) -> bool:
    if anchor < max(50, trend_lookback - 1, 3):
        return False
    values = [e20.iloc[anchor], e50.iloc[anchor], e20.iloc[anchor - 3], e50.iloc[anchor - 3]]
    if any(not _finite(v) for v in values):
        return False

    recent_high = float(df["High"].iloc[anchor - trend_lookback + 1 : anchor + 1].max())
    return (
        float(df["Close"].iloc[anchor]) > float(e20.iloc[anchor]) > float(e50.iloc[anchor])
        and float(e20.iloc[anchor]) > float(e20.iloc[anchor - 3])
        and float(e50.iloc[anchor]) > float(e50.iloc[anchor - 3])
        and float(df["High"].iloc[anchor]) >= recent_high
    )


def _landry_classic_state(
    df: pd.DataFrame,
    min_pullback_bars: int = 3,
    max_pullback_bars: int = 7,
    tick_size: float = 0.01,
) -> SetupCandidate | None:
    if len(df) < 60:
        return None

    close = df["Close"].astype(float)
    e20, e50 = ema(close, 20), ema(close, 50)
    last = len(df) - 1

    for count in range(max_pullback_bars, min_pullback_bars - 1, -1):
        anchor = last - count
        if anchor < 0 or not _classic_landry_anchor(df, e20, e50, anchor):
            continue
        if all(
            float(df["High"].iloc[i]) < float(df["High"].iloc[i - 1])
            for i in range(anchor + 1, last + 1)
        ):
            return SetupCandidate(
                name="Dave Landry",
                strength=2,
                status=f"Pullback clássico com {count} máximas descendentes",
                entry=float(df["High"].iloc[last]) + tick_size,
                stop=float(df["Low"].iloc[anchor + 1 : last + 1].min()) - tick_size,
                target=float(df["High"].iloc[anchor]),
            )

    # Pré-sinal: 2 barras de pullback já formadas após um anchor válido.
    count = max(1, min_pullback_bars - 1)
    anchor = last - count
    if anchor >= 0 and _classic_landry_anchor(df, e20, e50, anchor):
        if all(
            float(df["High"].iloc[i]) < float(df["High"].iloc[i - 1])
            for i in range(anchor + 1, last + 1)
        ):
            return SetupCandidate(
                name="Dave Landry",
                strength=1,
                status=f"Pullback em formação ({count}/{min_pullback_bars} barras)",
                entry=float(df["High"].iloc[last]) + tick_size,
                stop=float(df["Low"].iloc[anchor + 1 : last + 1].min()) - tick_size,
                target=float(df["High"].iloc[anchor]),
            )
    return None


def _setup_91_candidate(df: pd.DataFrame) -> SetupCandidate | None:
    e9 = ema(df["Close"].astype(float), 9)
    state = _setup_91_state(df, e9, "buy")
    if not state.get("passed", False):
        return None

    status = state.get("status", "")
    strength = 2
    return SetupCandidate(
        name="Setup 9.1",
        strength=strength,
        status=status,
        entry=state.get("entry"),
        stop=state.get("stop"),
    )


def _technical_region_score(df: pd.DataFrame) -> tuple[float, str]:
    close = df["Close"].astype(float)
    atr14 = atr(df, 14)
    atr_now = _series_value(atr14)
    close_now = _series_value(close)
    if atr_now is None or close_now is None or atr_now <= 0:
        return 0.0, "Sem ATR"

    means = [ema(close, period) for period in (21, 50, 80)]
    mean_values = [value for value in (_series_value(s) for s in means) if value is not None]
    near_mean = bool(mean_values) and min(abs(close_now - value) / atr_now for value in mean_values) <= 0.60

    if len(df) >= 21:
        prior_support = float(df["Low"].iloc[-21:-1].min())
        support_distance = (close_now - prior_support) / atr_now
        near_support = -0.25 <= support_distance <= 1.0
    else:
        prior_support = None
        near_support = False

    score = float(near_mean) + float(near_support)
    parts = []
    if near_mean:
        parts.append("próximo de MME21/50/80")
    if near_support and prior_support is not None:
        parts.append(f"próximo do suporte 20p ({prior_support:.2f})")
    return min(2.0, score), ", ".join(parts) if parts else "Sem confluência clara"


def _volume_score(df: pd.DataFrame) -> tuple[float, float | None]:
    if len(df) < 20:
        return 0.0, None
    volume = df["Volume"].astype(float)
    avg = float(volume.iloc[-20:].mean())
    if avg <= 0:
        return 0.0, None
    ratio = float(volume.iloc[-1]) / avg
    if ratio >= 1.20:
        return 1.0, ratio
    if ratio >= 0.80:
        return 0.5, ratio
    return 0.0, ratio


def _rr_for_candidate(candidate: SetupCandidate, fallback_target: float | None) -> tuple[float | None, float | None]:
    entry, stop = candidate.entry, candidate.stop
    target = candidate.target if candidate.target is not None else fallback_target
    if any(value is None or not _finite(value) for value in (entry, stop, target)):
        return None, target

    risk = float(entry) - float(stop)
    reward = float(target) - float(entry)
    if risk <= 0 or reward <= 0:
        return None, target
    return reward / risk, target


def _rr_score(rr: float | None) -> float:
    if rr is None:
        return 0.0
    if rr >= 2.0:
        return 2.0
    if rr >= 1.5:
        return 1.0
    if rr >= 1.0:
        return 0.5
    return 0.0


def _fallback_target(df: pd.DataFrame) -> float | None:
    if len(df) < 21:
        return None
    return float(df["High"].iloc[-21:-1].max())


def _priority(total: float, setup_score: float, aligned: bool) -> str:
    if total >= 7.0 and setup_score >= 2.0 and aligned:
        return "A"
    if total >= 5.0 and setup_score >= 1.0:
        return "B"
    return "C"


def evaluate_eod_latest(
    ticker: str,
    df: pd.DataFrame,
    higher_tf: pd.DataFrame,
    scan_mode: str,
) -> dict:
    if len(df) < 60:
        raise ValueError("Histórico insuficiente para o Checklist EOD.")

    trend_score, trend_label, _ = _trend_score(df)
    higher_score, higher_label, _ = _trend_score(higher_tf) if not higher_tf.empty else (0.0, "Sem dados", {})
    aligned = higher_score >= 1.0

    candidates: list[SetupCandidate] = []

    setup91 = _setup_91_candidate(df)
    if setup91:
        candidates.append(setup91)

    ifr2, rsi2_value = _ifr2_state(df)
    if ifr2:
        candidates.append(ifr2)

    mean_rev, distance_atr = _mean_reversion_state(df, trend_score)
    if mean_rev:
        candidates.append(mean_rev)

    landry = _landry_classic_state(df)
    if landry:
        candidates.append(landry)

    setup_score = float(max((c.strength for c in candidates), default=0))
    region_score, region_detail = _technical_region_score(df)
    volume_score, volume_ratio = _volume_score(df)

    fallback_target = _fallback_target(df)
    best_candidate = None
    best_rr = None
    best_target = None

    for candidate in candidates:
        rr, target = _rr_for_candidate(candidate, fallback_target)
        if best_candidate is None:
            best_candidate, best_rr, best_target = candidate, rr, target
            continue
        current_rr = -1 if rr is None else rr
        prior_rr = -1 if best_rr is None else best_rr
        if current_rr > prior_rr or (current_rr == prior_rr and candidate.strength > best_candidate.strength):
            best_candidate, best_rr, best_target = candidate, rr, target

    rr_score = _rr_score(best_rr)
    total = round(min(9.0, trend_score + setup_score + region_score + volume_score + rr_score), 1)
    priority = _priority(total, setup_score, aligned)

    adx_series, plus_di, minus_di = adx_components(df, 14)
    adx_value = _series_value(adx_series)

    setup_names = " + ".join(c.name for c in candidates) if candidates else "Nenhum"
    setup_status = " | ".join(f"{c.name}: {c.status}" for c in candidates) if candidates else "Sem setup ativo"

    return {
        "Ticker": ticker,
        "Prioridade": priority,
        "Nota": total,
        "Confluências": len(candidates),
        "Setups": setup_names,
        "Status": setup_status,
        "Tendência": trend_label,
        "Tendência maior": higher_label,
        "Alinhado": "Sim" if aligned else "Não",
        "IFR2": _round(rsi2_value, 1),
        "ADX14": _round(adx_value, 1),
        "Volume x média20": _round(volume_ratio, 2),
        "Dist. MME21 (ATR)": _round(distance_atr, 2),
        "Gatilho": _round(best_candidate.entry if best_candidate else None),
        "Stop": _round(best_candidate.stop if best_candidate else None),
        "Alvo técnico": _round(best_target),
        "R/R": _round(best_rr, 2),
        "Trend pts": trend_score,
        "Setup pts": setup_score,
        "Região pts": region_score,
        "Volume pts": volume_score,
        "R/R pts": rr_score,
        "Região técnica": region_detail,
        "Regime ADX": classify_trend(df),
        "Timeframe": scan_mode,
        "Data": pd.Timestamp(df.index[-1]).strftime("%d/%m/%Y"),
    }


def scan_eod_universe(
    tickers,
    provider,
    scan_mode: str = "Diário",
    period: str = "5y",
):
    if scan_mode not in {"Diário", "Semanal"}:
        raise ValueError("scan_mode deve ser 'Diário' ou 'Semanal'.")

    rows = []
    errors = {}
    histories = None

    if len(tickers) > 1 and hasattr(provider, "get_histories"):
        try:
            histories, batch_errors = provider.get_histories(list(tickers), period=period)
            errors.update(batch_errors)
        except Exception:
            histories = None
            errors = {}

    for ticker in tickers:
        try:
            if histories is None:
                raw = provider.get_history(ticker, period=period)
            else:
                raw = histories.get(ticker)
                if raw is None or raw.empty:
                    if ticker in errors:
                        continue
                    raise ValueError("Sem histórico disponível.")

            if scan_mode == "Diário":
                target = raw.copy()
                higher = _completed_resample(raw, "Semanal")
            else:
                target = _completed_resample(raw, "Semanal")
                higher = _completed_resample(raw, "Mensal")

            row = evaluate_eod_latest(ticker, target, higher, scan_mode)
            if raw.attrs.get("source"):
                row["Fonte"] = raw.attrs["source"]
                row["Último pregão"] = raw.attrs["latest_session"].strftime("%d/%m/%Y")
            rows.append(row)
            errors.pop(ticker, None)
        except Exception as exc:
            errors[ticker] = str(exc)

    if not rows:
        return pd.DataFrame(), errors

    result = pd.DataFrame(rows)
    priority_order = pd.Categorical(result["Prioridade"], categories=["A", "B", "C"], ordered=True)
    result = result.assign(_priority_order=priority_order)
    result = result.sort_values(
        by=["_priority_order", "Nota", "Confluências", "Ticker"],
        ascending=[True, False, False, True],
    ).drop(columns=["_priority_order"]).reset_index(drop=True)
    return result, errors
