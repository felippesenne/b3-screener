import unittest
from unittest.mock import patch

import pandas as pd

from backtest.engine import BacktestConfig
from backtest.ifr2_ifr14_rolling import run_ifr2_ifr14_rolling_backtest


class Ifr2Ifr14RollingTests(unittest.TestCase):
    def setUp(self):
        self.idx = pd.date_range("2026-01-02", periods=7, freq="B")
        self.df = pd.DataFrame(
            {
                "Open": [10.0, 10.2, 10.1, 10.15, 10.55, 10.60, 10.55],
                "High": [10.5, 10.4, 10.2, 10.5, 10.8, 10.9, 10.7],
                "Low": [9.8, 10.0, 9.95, 10.0, 10.4, 10.5, 10.45],
                "Close": [10.2, 10.1, 10.0, 10.4, 10.7, 10.8, 10.5],
                "Volume": [1_000_000] * 7,
            },
            index=self.idx,
        )
        self.rsi2 = pd.Series([20.0, 5.0, 6.0, 15.0, 30.0, 40.0, 45.0], index=self.idx)
        self.rsi14 = pd.Series([50.0, 55.0, 58.0, 60.0, 75.0, 76.0, 65.0], index=self.idx)

    def _fake_rsi(self, series, period):
        return self.rsi2 if period == 2 else self.rsi14

    def test_entry_trigger_rolls_down_and_exit_trigger_ratchets_up(self):
        cfg = BacktestConfig(initial_capital=10_000, position_size_pct=1.0)
        with patch("backtest.ifr2_ifr14_rolling.rsi_wilder", side_effect=self._fake_rsi):
            orders, result = run_ifr2_ifr14_rolling_backtest(self.df, cfg, tick_size=0.01)

        entries = orders[orders["Phase"] == "entry"].reset_index(drop=True)
        exits = orders[orders["Phase"] == "exit"].reset_index(drop=True)

        # IFR2 cruza abaixo de 10 no dia 1: gatilho inicial = máxima 10,40 + 0,01.
        self.assertAlmostEqual(entries.iloc[0]["TriggerPrice"], 10.41, places=8)
        # Não rompe no dia 2; para o dia 3 o gatilho cai para 10,20 + 0,01.
        self.assertAlmostEqual(entries.iloc[1]["TriggerPrice"], 10.21, places=8)
        self.assertEqual(pd.Timestamp(entries.iloc[1]["ReferenceDate"]), self.idx[2])

        self.assertEqual(len(result.trades), 1)
        trade = result.trades.iloc[0]
        self.assertAlmostEqual(trade["EntryPrice"], 10.21, places=8)

        # IFR14 cruza acima de 70 no dia 4: saída começa abaixo de 10,40.
        self.assertAlmostEqual(exits.iloc[0]["TriggerPrice"], 10.39, places=8)
        # Dia 5 não perde a referência e a mínima sobe para 10,50: stop sobe para 10,49.
        self.assertAlmostEqual(exits.iloc[1]["TriggerPrice"], 10.49, places=8)
        self.assertAlmostEqual(trade["ExitPrice"], 10.49, places=8)
        self.assertEqual(trade["ExitReason"], "ifr14_exit")

    def test_signals_require_threshold_crossing_not_just_remaining_beyond_level(self):
        rsi2 = pd.Series([5.0] * 7, index=self.idx)
        rsi14 = pd.Series([75.0] * 7, index=self.idx)

        def fake(series, period):
            return rsi2 if period == 2 else rsi14

        with patch("backtest.ifr2_ifr14_rolling.rsi_wilder", side_effect=fake):
            orders, result = run_ifr2_ifr14_rolling_backtest(
                self.df,
                BacktestConfig(initial_capital=10_000),
            )

        self.assertTrue(orders.empty)
        self.assertEqual(result.metrics["trades"], 0)

    def test_gap_entry_uses_open(self):
        df = self.df.copy()
        df.loc[self.idx[2], "Open"] = 10.60
        df.loc[self.idx[2], "High"] = 10.70
        with patch("backtest.ifr2_ifr14_rolling.rsi_wilder", side_effect=self._fake_rsi):
            _, result = run_ifr2_ifr14_rolling_backtest(
                df,
                BacktestConfig(initial_capital=10_000),
                tick_size=0.01,
            )
        self.assertGreaterEqual(len(result.trades), 1)
        self.assertAlmostEqual(result.trades.iloc[0]["EntryPrice"], 10.60, places=8)


if __name__ == "__main__":
    unittest.main()
