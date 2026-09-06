import operator
import pandas as pd

from indicators import resample_ohlcv, enrich

OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def evaluate_latest(ticker: str, df: pd.DataFrame, rules: dict) -> dict:
    latest = df.iloc[-1]
    checks = []

    if rules.get("use_rsi"):
        op = OPS[rules["rsi_operator"]]
        checks.append(op(float(latest["IFR2"]), float(rules["rsi_value"])))

    if rules.get("ema50_up"):
        checks.append(bool(latest["MME50_UP"]))

    if rules.get("ema9_up"):
        checks.append(bool(latest["MME9_UP"]))

    if rules.get("ema80_up"):
        checks.append(bool(latest["MME80_UP"]))

    if rules.get("price_above_ema200"):
        checks.append(bool(latest["PRICE_ABOVE_MME200"]))

    passed = all(checks) if checks else True

    return {
        "Ticker": ticker,
        "Fechamento": round(float(latest["Close"]), 2),
        "IFR2": round(float(latest["IFR2"]), 2),
        "MME9": round(float(latest["MME9"]), 2),
        "MME50": round(float(latest["MME50"]), 2),
        "MME80": round(float(latest["MME80"]), 2),
        "MME200": round(float(latest["MME200"]), 2),
        "MME9 ↑": bool(latest["MME9_UP"]),
        "MME50 ↑": bool(latest["MME50_UP"]),
        "MME80 ↑": bool(latest["MME80_UP"]),
        "Acima MME200": bool(latest["PRICE_ABOVE_MME200"]),
        "Data": df.index[-1].strftime("%d/%m/%Y"),
        "Passou": passed,
    }


def scan_universe(tickers, provider, timeframe, period, rules):
    rows = []
    errors = {}

    for ticker in tickers:
        try:
            raw = provider.get_history(ticker, period=period)
            tf = resample_ohlcv(raw, timeframe)
            calc = enrich(tf)

            if len(calc) < 3:
                raise ValueError("Histórico insuficiente para cálculo.")

            rows.append(evaluate_latest(ticker, calc, rules))

        except Exception as exc:
            errors[ticker] = str(exc)

    if not rows:
        return pd.DataFrame(), errors

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["Passou", "IFR2"],
        ascending=[False, True],
    ).reset_index(drop=True)

    return result, errors
