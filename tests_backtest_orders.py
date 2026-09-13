import unittest

import numpy as np
import pandas as pd

from backtest.engine import BacktestConfig
from backtest.order_engine import run_order_backtest
from backtest.setup_orders import compile_setup_orders


def _df(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-02", periods=len(rows), freq="B"))


class OrderEngineTests(unittest.TestCase):
    def test_long_stop_entry_and_same_bar_technical_stop(self):
        df = _df([
            {"Open": 10.0, "High": 10.2, "Low": 9.8, "Close": 10.0},
            {"Open": 10.0, "High": 11.0, "Low": 9.4, "Close": 10.2},
            {"Open": 10.2, "High": 10.4, "Low": 10.0, "Close": 10.3},
        ])
        orders = pd.DataFrame([
            {
                "ActiveDate": df.index[1],
                "OrderId": "L1",
                "Setup": "test",
                "Side": "long",
                "SignalDate": df.index[0],
                "TriggerPrice": 10.5,
                "StopPrice": 9.5,
            }
        ])
        result = run_order_backtest(df, orders, config=BacktestConfig(initial_capital=10_000))
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertAlmostEqual(float(trade["EntryPrice"]), 10.5, places=6)
        self.assertAlmostEqual(float(trade["ExitPrice"]), 9.5, places=6)
        self.assertEqual(trade["ExitReason"], "stop")
        self.assertEqual(trade["Side"], "long")

    def test_short_stop_entry_and_end_close(self):
        df = _df([
            {"Open": 10.0, "High": 10.2, "Low": 9.8, "Close": 10.0},
            {"Open": 10.0, "High": 10.1, "Low": 9.0, "Close": 9.2},
            {"Open": 9.1, "High": 9.3, "Low": 8.7, "Close": 8.8},
        ])
        orders = pd.DataFrame([
            {
                "ActiveDate": df.index[1],
                "OrderId": "S1",
                "Setup": "test",
                "Side": "short",
                "SignalDate": df.index[0],
                "TriggerPrice": 9.5,
                "StopPrice": 10.5,
            }
        ])
        result = run_order_backtest(df, orders, config=BacktestConfig(initial_capital=10_000))
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(trade["Side"], "short")
        self.assertAlmostEqual(float(trade["EntryPrice"]), 9.5, places=6)
        self.assertAlmostEqual(float(trade["ExitPrice"]), 8.8, places=6)
        self.assertGreater(float(trade["PnL"]), 0)

    def test_conservative_policy_cancels_ambiguous_bowtie_bar(self):
        df = _df([
            {"Open": 10.0, "High": 10.2, "Low": 9.8, "Close": 10.0},
            {"Open": 10.0, "High": 11.2, "Low": 9.6, "Close": 10.5},
        ])
        orders = pd.DataFrame([
            {
                "ActiveDate": df.index[1],
                "OrderId": "C1",
                "Setup": "bowtie_buy",
                "Side": "long",
                "SignalDate": df.index[0],
                "TriggerPrice": 11.0,
                "StopPrice": 9.0,
                "CancelBelow": 9.8,
            }
        ])
        result = run_order_backtest(df, orders, config=BacktestConfig(initial_capital=10_000))
        self.assertEqual(len(result.trades), 0)


class SetupCompilerTests(unittest.TestCase):
    def test_pfr_buy_is_active_only_on_next_bar(self):
        df = _df([
            {"Open": 10.0, "High": 10.8, "Low": 9.5, "Close": 10.2},
            {"Open": 10.1, "High": 10.6, "Low": 9.3, "Close": 9.8},
            {"Open": 9.8, "High": 10.5, "Low": 9.0, "Close": 10.0},
            {"Open": 10.0, "High": 10.7, "Low": 9.8, "Close": 10.6},
        ])
        orders = compile_setup_orders(df, "pfr_buy")
        self.assertEqual(len(orders), 1)
        order = orders.iloc[0]
        self.assertEqual(pd.Timestamp(order["ActiveDate"]), df.index[3])
        self.assertAlmostEqual(float(order["TriggerPrice"]), 10.51, places=6)
        self.assertAlmostEqual(float(order["StopPrice"]), 8.99, places=6)

    def test_setup_123_buy_uses_middle_bar_as_stop_reference(self):
        df = _df([
            {"Open": 10.2, "High": 10.8, "Low": 10.0, "Close": 10.3},
            {"Open": 10.0, "High": 10.4, "Low": 9.0, "Close": 9.5},
            {"Open": 9.4, "High": 10.2, "Low": 9.5, "Close": 10.0},
            {"Open": 10.0, "High": 10.5, "Low": 9.9, "Close": 10.4},
        ])
        orders = compile_setup_orders(df, "setup_123_buy")
        self.assertEqual(len(orders), 1)
        order = orders.iloc[0]
        self.assertAlmostEqual(float(order["TriggerPrice"]), 10.21, places=6)
        self.assertAlmostEqual(float(order["StopPrice"]), 8.99, places=6)

    def test_landry_simple_can_keep_order_for_configured_number_of_bars(self):
        df = _df([
            {"Open": 10.0, "High": 10.8, "Low": 9.5, "Close": 10.2},
            {"Open": 10.1, "High": 10.7, "Low": 9.3, "Close": 10.0},
            {"Open": 9.9, "High": 10.5, "Low": 9.0, "Close": 9.7},
            {"Open": 9.8, "High": 10.4, "Low": 9.4, "Close": 9.9},
            {"Open": 9.9, "High": 10.7, "Low": 9.6, "Close": 10.5},
        ])
        orders = compile_setup_orders(df, "landry_simple_buy", landry_valid_bars=2)
        first_id = orders.iloc[0]["OrderId"]
        same_order = orders[orders["OrderId"] == first_id]
        self.assertEqual(len(same_order), 2)
        self.assertAlmostEqual(float(same_order.iloc[0]["TriggerPrice"]), 10.51, places=6)

    def test_setup_91_buy_creates_persistent_trigger_until_filled(self):
        close = [12.0, 11.0, 10.0, 9.0, 8.0, 15.0, 16.0, 17.0]
        df = pd.DataFrame(
            {
                "Open": [v - 0.2 for v in close],
                "High": [v + 0.5 for v in close],
                "Low": [v - 0.5 for v in close],
                "Close": close,
            },
            index=pd.date_range("2026-01-02", periods=len(close), freq="B"),
        )
        orders = compile_setup_orders(df, "setup_91_buy")
        self.assertGreaterEqual(len(orders), 1)
        first = orders.iloc[0]
        self.assertEqual(pd.Timestamp(first["SignalDate"]), df.index[5])
        self.assertAlmostEqual(float(first["TriggerPrice"]), 15.51, places=6)
        self.assertAlmostEqual(float(first["StopPrice"]), 14.49, places=6)

    def test_bowtie_buy_detects_transition_pullback_and_rolling_trigger(self):
        close = list(np.linspace(30, 20, 20)) + [21, 23, 26, 30, 35, 36, 36.5, 37, 39, 40]
        opens = [v - 0.2 for v in close]
        highs = [v + 0.5 for v in close]
        lows = [v - 0.5 for v in close]
        lows[28] = 35.0
        df = pd.DataFrame(
            {"Open": opens, "High": highs, "Low": lows, "Close": close},
            index=pd.date_range("2026-01-02", periods=len(close), freq="B"),
        )
        orders = compile_setup_orders(df, "bowtie_buy", bowtie_transition_bars=4)
        self.assertGreaterEqual(len(orders), 1)
        first = orders.iloc[0]
        self.assertEqual(first["Setup"], "bowtie_buy")
        self.assertEqual(first["Side"], "long")
        self.assertEqual(pd.Timestamp(first["SignalDate"]), df.index[28])
        self.assertEqual(pd.Timestamp(first["ActiveDate"]), df.index[29])
        self.assertAlmostEqual(float(first["TriggerPrice"]), float(df["High"].iloc[28]) + 0.01, places=6)
        self.assertAlmostEqual(float(first["StopPrice"]), 34.99, places=6)
        self.assertFalse(pd.isna(first["CancelBelow"]))


if __name__ == "__main__":
    unittest.main()
