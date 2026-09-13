from __future__ import annotations

import pandas as pd

from backtest.trade_chart import build_operational_chart_frame, operational_chart_spec


def sample_ohlc() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {
            "Open": [10.0, 10.2, 10.5, 10.8, 11.0],
            "High": [10.4, 10.7, 11.0, 11.2, 11.3],
            "Low": [9.8, 10.0, 10.3, 10.6, 10.7],
            "Close": [10.2, 10.5, 10.8, 11.0, 10.9],
        },
        index=idx,
    )


def test_dynamic_trailing_stop_and_events():
    df = sample_ohlc()
    idx = df.index
    trades = pd.DataFrame(
        [
            {
                "EntryDate": idx[1],
                "ExitDate": idx[4],
                "EntryPrice": 10.30,
                "ExitPrice": 10.85,
                "InitialStop": 9.95,
                "ExitReason": "atr_stop",
            }
        ]
    )
    equity = pd.DataFrame(
        {
            "Equity": [100000, 100000, 100200, 100400, 100500],
            "TrailingStop": [None, 9.95, 10.05, 10.30, 10.85],
        },
        index=idx,
    )

    chart = build_operational_chart_frame(df, trades, equity).set_index("Date")
    assert chart.loc[idx[1], "EntryPrice"] == 10.30
    assert chart.loc[idx[1], "InitialStopPoint"] == 9.95
    assert chart.loc[idx[3], "ActiveStop"] == 10.30
    assert chart.loc[idx[4], "ExitPrice"] == 10.85
    assert chart.loc[idx[4], "StopHitPrice"] == 10.85


def test_static_stop_fallback_and_partial_exit():
    df = sample_ohlc()
    idx = df.index
    trades = pd.DataFrame(
        [
            {
                "EntryDate": idx[0],
                "ExitDate": idx[4],
                "EntryPrice": 10.10,
                "InitialStopPrice": 9.70,
                "PartialExitDate": idx[2],
                "PartialExitPrice": 10.90,
                "FinalExitPrice": 10.80,
                "ExitReason": "signal",
            }
        ]
    )

    chart = build_operational_chart_frame(df, trades, None).set_index("Date")
    assert chart.loc[idx[2], "PartialExitPrice"] == 10.90
    assert chart.loc[idx[4], "ExitPrice"] == 10.80
    assert chart.loc[idx[3], "ActiveStop"] == 9.70
    assert pd.isna(chart.loc[idx[4], "StopHitPrice"])


def test_vega_spec_contains_all_event_layers():
    spec = operational_chart_spec()
    layers = spec["layer"]
    serialized = str(layers)
    for field in ["EntryPrice", "ExitPrice", "PartialExitPrice", "StopHitPrice", "InitialStopPoint", "ActiveStop"]:
        assert field in serialized


if __name__ == "__main__":
    test_dynamic_trailing_stop_and_events()
    test_static_stop_fallback_and_partial_exit()
    test_vega_spec_contains_all_event_layers()
    print("OK")
