from __future__ import annotations

import pandas as pd

from backtest.trade_chart import (
    build_operational_chart_frame,
    build_operational_figure,
    slice_trade_window,
)


def sample_ohlc(periods: int = 30) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=periods, freq="D")
    close = pd.Series([10.0 + i * 0.08 + ((i % 5) - 2) * 0.05 for i in range(periods)], index=idx)
    return pd.DataFrame(
        {
            "Open": close - 0.04,
            "High": close + 0.20,
            "Low": close - 0.20,
            "Close": close,
        },
        index=idx,
    )


def test_dynamic_trailing_stop_and_events():
    df = sample_ohlc(8)
    idx = df.index
    trades = pd.DataFrame(
        [
            {
                "EntryDate": idx[1],
                "ExitDate": idx[6],
                "EntryPrice": 10.30,
                "ExitPrice": 10.85,
                "InitialStop": 9.95,
                "ExitReason": "atr_stop",
                "Setup": "landry_adjusted_buy",
            }
        ]
    )
    equity = pd.DataFrame(
        {
            "Equity": [100000, 100000, 100200, 100400, 100500, 100550, 100600, 100600],
            "TrailingStop": [None, 9.95, 10.05, 10.30, 10.45, 10.60, 10.85, None],
        },
        index=idx,
    )

    chart = build_operational_chart_frame(df, trades, equity).set_index("Date")
    assert chart.loc[idx[1], "EntryPrice"] == 10.30
    assert chart.loc[idx[1], "InitialStopPoint"] == 9.95
    assert chart.loc[idx[3], "ActiveStop"] == 10.30
    assert chart.loc[idx[6], "ExitPrice"] == 10.85
    assert chart.loc[idx[6], "StopHitPrice"] == 10.85
    assert "MMS10" in chart.columns
    assert "MME20" in chart.columns
    assert "MME30" in chart.columns


def test_static_stop_fallback_and_partial_exit():
    df = sample_ohlc(8)
    idx = df.index
    trades = pd.DataFrame(
        [
            {
                "EntryDate": idx[0],
                "ExitDate": idx[6],
                "EntryPrice": 10.10,
                "InitialStopPrice": 9.70,
                "PartialExitDate": idx[3],
                "PartialExitPrice": 10.90,
                "FinalExitPrice": 10.80,
                "ExitReason": "signal",
                "Setup": "setup_91_buy",
            }
        ]
    )

    chart = build_operational_chart_frame(df, trades, None).set_index("Date")
    assert chart.loc[idx[3], "PartialExitPrice"] == 10.90
    assert chart.loc[idx[6], "ExitPrice"] == 10.80
    assert chart.loc[idx[4], "ActiveStop"] == 9.70
    assert pd.isna(chart.loc[idx[6], "StopHitPrice"])
    assert "MME9" in chart.columns


def test_ifr_panel_and_rolling_triggers_are_in_chart_frame_and_figure():
    df = sample_ohlc(35)
    idx = df.index
    trades = pd.DataFrame(
        [
            {
                "EntryDate": idx[17],
                "ExitDate": idx[26],
                "EntrySignalDate": idx[15],
                "ExitSignalDate": idx[24],
                "EntryPrice": 11.25,
                "ExitPrice": 11.80,
                "ExitReason": "ifr14_exit",
                "Setup": "ifr2_ifr14_rolling_buy",
            }
        ]
    )
    orders = pd.DataFrame(
        [
            {"Phase": "entry", "ActiveDate": idx[16], "TriggerPrice": 11.40},
            {"Phase": "entry", "ActiveDate": idx[17], "TriggerPrice": 11.30},
            {"Phase": "exit", "ActiveDate": idx[25], "TriggerPrice": 11.70},
            {"Phase": "exit", "ActiveDate": idx[26], "TriggerPrice": 11.78},
        ]
    )

    chart = build_operational_chart_frame(
        df,
        trades,
        orders=orders,
        setup_id="ifr2_ifr14_rolling_buy",
    )
    indexed = chart.set_index("Date")
    assert indexed.loc[idx[16], "EntryTrigger"] == 11.40
    assert indexed.loc[idx[17], "EntryTrigger"] == 11.30
    assert indexed.loc[idx[25], "ExitTrigger"] == 11.70
    assert indexed.loc[idx[26], "ExitTrigger"] == 11.78
    assert "IFR2" in chart.columns
    assert "IFR14" in chart.columns
    assert chart["IFR14"].notna().any()

    fig = build_operational_figure(
        chart,
        setup_id="ifr2_ifr14_rolling_buy",
        selected_trade=trades.iloc[0],
    )
    trace_names = {trace.name for trace in fig.data}
    assert "Preço" in trace_names
    assert "Gatilho de entrada" in trace_names
    assert "Gatilho de saída" in trace_names
    assert "IFR2" in trace_names
    assert "IFR14" in trace_names
    assert fig.layout.yaxis2.range == (0, 100)


def test_trade_window_focuses_around_selected_operation():
    df = sample_ohlc(40)
    idx = df.index
    trade = pd.Series({"EntryDate": idx[15], "ExitDate": idx[20]})
    chart = build_operational_chart_frame(df, pd.DataFrame())
    window = slice_trade_window(chart, trade, padding_bars=4)
    assert window.iloc[0]["Date"] == idx[11]
    assert window.iloc[-1]["Date"] == idx[24]


if __name__ == "__main__":
    test_dynamic_trailing_stop_and_events()
    test_static_stop_fallback_and_partial_exit()
    test_ifr_panel_and_rolling_triggers_are_in_chart_frame_and_figure()
    test_trade_window_focuses_around_selected_operation()
    print("OK")
