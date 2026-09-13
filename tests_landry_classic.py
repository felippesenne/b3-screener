import unittest

import pandas as pd

from backtest.engine import BacktestConfig
from backtest.landry_classic_engine import run_landry_classic_backtest
from backtest.landry_classic_setup import compile_landry_classic_orders
from backtest.ui_helpers import SETUP_LABELS


class LandryClassicTests(unittest.TestCase):
    def test_classic_compiler_builds_rolling_trigger_after_three_lower_highs(self):
        idx = pd.date_range("2026-01-02", periods=70, freq="B")
        close = [10.0 + i * 0.16 for i in range(70)]
        df = pd.DataFrame(
            {
                "Open": close,
                "High": [v + 0.30 for v in close],
                "Low": [v - 0.30 for v in close],
                "Close": close,
                "Volume": [1_000_000] * 70,
            },
            index=idx,
        )

        # Anchor at 60 is a fresh high inside an established EMA20 > EMA50 uptrend.
        df.iloc[60, df.columns.get_loc("Open")] = 20.0
        df.iloc[60, df.columns.get_loc("High")] = 20.50
        df.iloc[60, df.columns.get_loc("Low")] = 19.90
        df.iloc[60, df.columns.get_loc("Close")] = 20.20

        # Four consecutive lower highs. The first actionable order appears after
        # the third bar, then the trigger rolls lower on the next bar.
        bars = {
            61: (20.10, 20.30, 19.80, 20.05),
            62: (20.00, 20.20, 19.70, 19.95),
            63: (19.90, 20.10, 19.60, 19.90),
            64: (19.90, 20.00, 19.70, 19.95),
            65: (20.00, 20.50, 19.85, 20.40),
        }
        for i, values in bars.items():
            df.iloc[i, df.columns.get_loc("Open")] = values[0]
            df.iloc[i, df.columns.get_loc("High")] = values[1]
            df.iloc[i, df.columns.get_loc("Low")] = values[2]
            df.iloc[i, df.columns.get_loc("Close")] = values[3]

        rows = compile_landry_classic_orders(
            df,
            "landry_classic_buy",
            "long",
            tick_size=0.01,
            min_pullback_bars=3,
            max_pullback_bars=7,
            trend_lookback=20,
        )
        self.assertGreaterEqual(len(rows), 2)
        first, second = rows[0], rows[1]
        self.assertEqual(first["ActiveDate"], idx[64])
        self.assertAlmostEqual(first["TriggerPrice"], 20.11, places=6)
        self.assertAlmostEqual(first["StopPrice"], 19.59, places=6)
        self.assertEqual(second["ActiveDate"], idx[65])
        self.assertAlmostEqual(second["TriggerPrice"], 20.01, places=6)
        self.assertEqual(first["OrderId"], second["OrderId"])

    def test_classic_compiler_rejects_pullback_without_prior_trend_extreme(self):
        idx = pd.date_range("2026-01-02", periods=70, freq="B")
        close = [20.0 - i * 0.05 for i in range(70)]
        df = pd.DataFrame(
            {
                "Open": close,
                "High": [v + 0.30 for v in close],
                "Low": [v - 0.30 for v in close],
                "Close": close,
                "Volume": [1_000_000] * 70,
            },
            index=idx,
        )
        rows = compile_landry_classic_orders(df, "landry_classic_buy", "long")
        self.assertEqual(rows, [])

    def test_landry_management_takes_half_at_one_r_then_trails_runner(self):
        idx = pd.date_range("2026-01-02", periods=4, freq="B")
        df = pd.DataFrame(
            {
                "Open": [9.80, 10.50, 11.20, 11.00],
                "High": [10.20, 11.20, 11.50, 11.10],
                "Low": [9.50, 10.20, 10.80, 10.10],
                "Close": [10.10, 11.10, 11.30, 10.30],
                "Volume": [1_000_000] * 4,
            },
            index=idx,
        )
        orders = pd.DataFrame(
            [
                {
                    "ActiveDate": idx[0],
                    "OrderId": "landry:1",
                    "Setup": "landry_classic_buy",
                    "Side": "long",
                    "SignalDate": idx[0] - pd.Timedelta(days=1),
                    "TriggerPrice": 10.0,
                    "StopPrice": 9.0,
                    "CancelBelow": None,
                    "CancelAbove": None,
                }
            ]
        )
        result = run_landry_classic_backtest(
            df,
            orders,
            config=BacktestConfig(initial_capital=1000.0, position_size_pct=1.0),
            trailing_bars=2,
            tick_size=0.01,
        )
        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertEqual(int(trade["Quantity"]), 100)
        self.assertEqual(int(trade["PartialQuantity"]), 50)
        self.assertEqual(int(trade["FinalQuantity"]), 50)
        self.assertAlmostEqual(float(trade["PartialExitPrice"]), 11.0, places=6)
        self.assertAlmostEqual(float(trade["FinalExitPrice"]), 10.19, places=6)
        self.assertEqual(trade["ExitReason"], "runner_trailing_stop")
        self.assertAlmostEqual(float(trade["PnL"]), 59.5, places=6)
        self.assertAlmostEqual(float(trade["RMultiple"]), 0.595, places=6)

    def test_ui_exposes_classic_and_keeps_simplified_landry(self):
        ids = set(SETUP_LABELS.values())
        self.assertIn("landry_classic_buy", ids)
        self.assertIn("landry_classic_sell", ids)
        self.assertIn("landry_simple_buy", ids)
        self.assertIn("landry_simple_sell", ids)


if __name__ == "__main__":
    unittest.main()
