import unittest

import pandas as pd

from backtest import BacktestConfig, run_backtest


class BacktestEngineTests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range("2026-01-05", periods=5, freq="B")

    def test_signal_executes_only_on_next_open(self):
        df = pd.DataFrame(
            {
                "Open": [10.0, 11.0, 12.0, 13.0, 14.0],
                "High": [10.5, 11.5, 12.5, 13.5, 14.5],
                "Low": [9.5, 10.5, 11.5, 12.5, 13.5],
                "Close": [10.2, 11.2, 12.2, 13.2, 14.2],
            },
            index=self.idx,
        )
        entry = pd.Series([True, False, False, False, False], index=self.idx)
        result = run_backtest(df, entry, config=BacktestConfig(initial_capital=1_000))
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades.iloc[0]["EntryDate"], self.idx[1])
        self.assertAlmostEqual(result.trades.iloc[0]["EntryPrice"], 11.0)

    def test_gap_below_stop_exits_at_open_not_stop_level(self):
        df = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 85.0, 86.0, 87.0],
                "High": [101.0, 101.0, 90.0, 88.0, 89.0],
                "Low": [99.0, 99.0, 84.0, 84.0, 85.0],
                "Close": [100.0, 100.0, 86.0, 87.0, 88.0],
            },
            index=self.idx,
        )
        entry = pd.Series([True, False, False, False, False], index=self.idx)
        result = run_backtest(
            df,
            entry,
            config=BacktestConfig(initial_capital=10_000, stop_loss_pct=0.10),
        )
        trade = result.trades.iloc[0]
        self.assertEqual(trade["ExitReason"], "stop_gap")
        self.assertAlmostEqual(trade["ExitPrice"], 85.0)

    def test_commission_and_slippage_reduce_result(self):
        df = pd.DataFrame(
            {
                "Open": [10.0, 10.0, 11.0, 11.0, 11.0],
                "High": [10.0, 10.5, 11.5, 11.5, 11.5],
                "Low": [10.0, 9.5, 10.5, 10.5, 10.5],
                "Close": [10.0, 10.0, 11.0, 11.0, 11.0],
            },
            index=self.idx,
        )
        entry = pd.Series([True, False, False, False, False], index=self.idx)
        clean = run_backtest(df, entry, config=BacktestConfig(initial_capital=1_000))
        costly = run_backtest(
            df,
            entry,
            config=BacktestConfig(initial_capital=1_000, commission_bps=10, slippage_bps=10),
        )
        self.assertLess(costly.metrics["final_equity"], clean.metrics["final_equity"])

    def test_exit_signal_also_executes_next_open(self):
        df = pd.DataFrame(
            {
                "Open": [10.0, 10.0, 12.0, 13.0, 14.0],
                "High": [10.5, 10.5, 12.5, 13.5, 14.5],
                "Low": [9.5, 9.5, 11.5, 12.5, 13.5],
                "Close": [10.0, 10.0, 12.0, 13.0, 14.0],
            },
            index=self.idx,
        )
        entry = pd.Series([True, False, False, False, False], index=self.idx)
        exit_ = pd.Series([False, True, False, False, False], index=self.idx)
        result = run_backtest(df, entry, exit_, BacktestConfig(initial_capital=1_000))
        trade = result.trades.iloc[0]
        self.assertEqual(trade["EntryDate"], self.idx[1])
        self.assertEqual(trade["ExitDate"], self.idx[2])
        self.assertAlmostEqual(trade["ExitPrice"], 12.0)


if __name__ == "__main__":
    unittest.main()
