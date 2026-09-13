import pandas as pd

from classic_setups import evaluate_context_filter, special_setup_state


def _df(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="D"))


def test_landry_buy_uses_only_current_low_vs_previous_two():
    df = _df([
        {"Open": 10.0, "High": 11.0, "Low": 9.5, "Close": 10.5, "Volume": 100},
        {"Open": 10.4, "High": 10.9, "Low": 9.3, "Close": 10.0, "Volume": 100},
        {"Open": 9.9, "High": 10.5, "Low": 9.0, "Close": 9.7, "Volume": 100},
    ])
    state = special_setup_state(df, "landry_simple_buy", df["Close"])
    assert state["passed"] is True


def test_landry_sell_is_mirrored_on_highs():
    df = _df([
        {"Open": 10.0, "High": 10.5, "Low": 9.5, "Close": 10.0, "Volume": 100},
        {"Open": 10.0, "High": 10.7, "Low": 9.6, "Close": 10.2, "Volume": 100},
        {"Open": 10.2, "High": 11.0, "Low": 9.8, "Close": 10.4, "Volume": 100},
    ])
    state = special_setup_state(df, "landry_simple_sell", df["Close"])
    assert state["passed"] is True


def test_sma_205080_context_filter():
    close = [100 + i * 0.5 for i in range(100)]
    df = pd.DataFrame(
        {
            "Open": close,
            "High": [v + 1 for v in close],
            "Low": [v - 1 for v in close],
            "Close": close,
            "Volume": [100] * len(close),
        },
        index=pd.date_range("2026-01-01", periods=len(close), freq="D"),
    )
    passed, _ = evaluate_context_filter(df, "MMS20/50/80 ascendentes")
    assert passed is True


if __name__ == "__main__":
    test_landry_buy_uses_only_current_low_vs_previous_two()
    test_landry_sell_is_mirrored_on_highs()
    test_sma_205080_context_filter()
    print("ok")
