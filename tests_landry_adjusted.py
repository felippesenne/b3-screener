from __future__ import annotations

import pandas as pd

from backtest.engine import BacktestConfig
from backtest.landry_adjusted_engine import run_landry_adjusted_backtest
from backtest.landry_adjusted_setup import compile_landry_adjusted_orders


def _trend_df(n: int = 45) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    close = pd.Series([100.0 + i * 0.5 for i in range(n)], index=idx)
    df = pd.DataFrame(index=idx)
    df["Open"] = close - 0.20
    df["High"] = close + 0.50
    df["Low"] = close - 0.50
    df["Close"] = close
    df["Volume"] = 1_000_000
    return df


def test_order_rules_and_one_bar_validity():
    df = _trend_df()
    signal_i = 32
    df.iloc[signal_i, df.columns.get_loc("Low")] = float(df["Low"].iloc[signal_i - 2:signal_i].min()) - 0.25

    orders = compile_landry_adjusted_orders(df)
    match = orders[orders["SignalDate"] == df.index[signal_i]]
    assert len(match) == 1
    order = match.iloc[0]

    assert order["ActiveDate"] == df.index[signal_i + 1]
    assert abs(float(order["TriggerPrice"]) - (float(df["High"].iloc[signal_i]) + 0.01)) < 1e-9
    assert abs(float(order["StopPrice"]) - (float(df["Low"].iloc[signal_i]) - 0.05)) < 1e-9
    assert order["Side"] == "long"


def test_signal_requires_all_three_averages_rising():
    df = _trend_df()
    signal_i = 32
    df.iloc[signal_i, df.columns.get_loc("Low")] = float(df["Low"].iloc[signal_i - 2:signal_i].min()) - 0.25

    # Derruba o fechamento do candle-sinal o suficiente para fazer a MMA10 virar,
    # mantendo o padrão de mínima. O setup não deve gerar ordem nesse candle.
    df.iloc[signal_i, df.columns.get_loc("Close")] = float(df["Close"].iloc[signal_i - 1]) - 8.0
    orders = compile_landry_adjusted_orders(df)
    assert not bool((orders["SignalDate"] == df.index[signal_i]).any())


def test_initial_stop_on_entry_bar_then_atr_trailing_from_next_bar():
    idx = pd.date_range("2026-01-01", periods=26, freq="D")
    df = pd.DataFrame(
        {
            "Open": [100.0] * 26,
            "High": [101.0] * 26,
            "Low": [99.0] * 26,
            "Close": [100.0] * 26,
            "Volume": [1_000_000] * 26,
        },
        index=idx,
    )

    # Candle de entrada: o low 97 ficaria abaixo de um ATR-stop apertado, mas está
    # acima do stop inicial 95. O teste garante que o ATR não atua no candle de entrada.
    df.loc[idx[20], ["Open", "High", "Low", "Close"]] = [100.0, 102.0, 97.0, 101.0]
    df.loc[idx[21], ["Open", "High", "Low", "Close"]] = [101.0, 104.0, 100.0, 103.0]
    df.loc[idx[22], ["Open", "High", "Low", "Close"]] = [103.0, 105.0, 100.5, 104.0]
    df.loc[idx[23], ["Open", "High", "Low", "Close"]] = [102.0, 103.0, 99.0, 100.0]

    orders = pd.DataFrame(
        [
            {
                "ActiveDate": idx[20],
                "OrderId": "landry_adjusted_buy:test",
                "Setup": "landry_adjusted_buy",
                "Side": "long",
                "SignalDate": idx[19],
                "TriggerPrice": 100.50,
                "StopPrice": 95.00,
                "CancelBelow": None,
                "CancelAbove": None,
            }
        ]
    )

    result = run_landry_adjusted_backtest(
        df,
        orders,
        config=BacktestConfig(initial_capital=100_000.0, position_size_pct=1.0),
        atr_period=20,
        atr_multiplier=2.0,
    )

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["EntryDate"] == idx[20]
    assert trade["ExitDate"] > idx[20]
    assert trade["ExitReason"] in {"atr_stop", "atr_stop_gap"}
    assert float(trade["InitialStop"]) == 95.0
    assert float(trade["FinalStop"]) >= float(trade["InitialStop"])


if __name__ == "__main__":
    test_order_rules_and_one_bar_validity()
    test_signal_requires_all_three_averages_rising()
    test_initial_stop_on_entry_bar_then_atr_trailing_from_next_bar()
    print("OK — Dave Landry ajustado")
