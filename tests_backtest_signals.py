import unittest

import pandas as pd

from backtest import compile_rules_signal
from scanner import evaluate_latest


class BacktestSignalCompilerTests(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2026-01-02", periods=40, freq="B")
        close = [100 + ((i % 7) - 3) * 0.8 + i * 0.25 for i in range(len(idx))]
        self.df = pd.DataFrame(
            {
                "Open": [c - 0.2 for c in close],
                "High": [c + 0.8 for c in close],
                "Low": [c - 0.9 for c in close],
                "Close": close,
                "Volume": [1_000_000 + i * 10_000 for i in range(len(idx))],
            },
            index=idx,
        )

    def test_compiler_matches_screener_for_generic_rules(self):
        rules = [
            {
                "left": {"kind": "EMA", "period": 5},
                "operator": "rising",
                "right_kind": "value",
                "right_value": 0,
            },
            {
                "connector": "AND",
                "left": {"kind": "RSI", "period": 2},
                "operator": ">",
                "right_kind": "value",
                "right_value": 45,
            },
        ]
        compiled = compile_rules_signal(self.df, rules)

        expected = []
        for i in range(len(self.df)):
            prefix = self.df.iloc[: i + 1]
            try:
                row = evaluate_latest("TEST", prefix, rules)
                expected.append(bool(row["Estratégia OK"]))
            except Exception:
                expected.append(False)

        self.assertEqual(compiled.tolist(), expected)

    def test_cross_above_matches_screener(self):
        rules = [
            {
                "left": {"kind": "EMA", "period": 3},
                "operator": "crosses_above",
                "right_kind": "indicator",
                "right": {"kind": "EMA", "period": 8},
            }
        ]
        compiled = compile_rules_signal(self.df, rules)
        expected = []
        for i in range(len(self.df)):
            prefix = self.df.iloc[: i + 1]
            try:
                row = evaluate_latest("TEST", prefix, rules)
                expected.append(bool(row["Estratégia OK"]))
            except Exception:
                expected.append(False)
        self.assertEqual(compiled.tolist(), expected)

    def test_trigger_setups_are_rejected_until_order_adapter_exists(self):
        rules = [
            {
                "left": {"kind": "EMA", "period": 9},
                "operator": "setup_91_buy",
                "right_kind": "value",
                "right_value": 0,
            }
        ]
        with self.assertRaises(NotImplementedError):
            compile_rules_signal(self.df, rules)


if __name__ == "__main__":
    unittest.main()
