import unittest

import pandas as pd

from backtest.ui_helpers import (
    EXIT_LABELS,
    SETUP_LABELS,
    build_exit_rules,
    run_setup_backtest_from_history,
    setup_side,
    summary_row,
)


class UiHelperTests(unittest.TestCase):
    def test_setup_labels_have_both_directions(self):
        ids = set(SETUP_LABELS.values())
        self.assertIn("setup_91_buy", ids)
        self.assertIn("setup_91_sell", ids)
        self.assertIn("bowtie_buy", ids)
        self.assertIn("bowtie_sell", ids)
        self.assertEqual(setup_side("pfr_buy"), "long")
        self.assertEqual(setup_side("pfr_sell"), "short")

    def test_exit_rules_are_direction_aware(self):
        long_rules = build_exit_rules("Fechamento cruza a MME9 contra a posição", "setup_91_buy")
        short_rules = build_exit_rules("Fechamento cruza a MME9 contra a posição", "setup_91_sell")
        self.assertEqual(long_rules[0]["operator"], "crosses_below")
        self.assertEqual(short_rules[0]["operator"], "crosses_above")

        long_rsi = build_exit_rules("IFR(2) retorna para 70/30", "pfr_buy")
        short_rsi = build_exit_rules("IFR(2) retorna para 70/30", "pfr_sell")
        self.assertEqual(long_rsi[0]["operator"], ">")
        self.assertEqual(long_rsi[0]["right_value"], 70.0)
        self.assertEqual(short_rsi[0]["operator"], "<")
        self.assertEqual(short_rsi[0]["right_value"], 30.0)

    def test_end_to_end_ui_runner(self):
        idx = pd.date_range("2026-01-02", periods=6, freq="B")
        raw = pd.DataFrame(
            {
                "Open": [10.0, 10.1, 9.8, 10.0, 10.7, 10.8],
                "High": [10.8, 10.6, 10.5, 10.8, 11.0, 11.1],
                "Low": [9.5, 9.3, 9.0, 9.8, 10.3, 10.5],
                "Close": [10.2, 9.8, 10.0, 10.7, 10.8, 11.0],
                "Volume": [1_000_000] * 6,
            },
            index=idx,
        )

        df, orders, result = run_setup_backtest_from_history(
            raw,
            setup_id="pfr_buy",
            timeframe="Diário",
            capital=10_000,
            position_size_pct=1.0,
            commission_bps=0.0,
            slippage_bps=0.0,
            take_profit_pct=None,
            exit_label=EXIT_LABELS[0],
        )
        self.assertEqual(len(df), 6)
        self.assertGreaterEqual(len(orders), 1)
        self.assertGreaterEqual(result.metrics["trades"], 1)
        row = summary_row("TEST3", result, len(orders))
        self.assertEqual(row["Ticker"], "TEST3")
        self.assertEqual(row["Trades"], result.metrics["trades"])


if __name__ == "__main__":
    unittest.main()
