import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backtest.cli import main


class FakeProvider:
    def get_history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        idx = pd.date_range("2026-01-02", periods=8, freq="B")
        close = [10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5]
        return pd.DataFrame(
            {
                "Open": [c - 0.1 for c in close],
                "High": [c + 0.3 for c in close],
                "Low": [c - 0.3 for c in close],
                "Close": close,
                "Volume": [1_000_000] * len(idx),
            },
            index=idx,
        )


class SetupProvider:
    def get_history(self, ticker: str, period: str = "5y") -> pd.DataFrame:
        idx = pd.date_range("2026-02-02", periods=5, freq="B")
        return pd.DataFrame(
            {
                "Open": [10.0, 10.1, 9.8, 10.0, 10.6],
                "High": [10.8, 10.6, 10.5, 10.8, 10.9],
                "Low": [9.5, 9.3, 9.0, 9.8, 10.2],
                "Close": [10.2, 9.8, 10.0, 10.7, 10.8],
                "Volume": [1_000_000] * len(idx),
            },
            index=idx,
        )


class BacktestCliTests(unittest.TestCase):
    def test_cli_runs_without_network_and_writes_outputs(self):
        rules = [
            {
                "left": {"kind": "PRICE", "field": "Close"},
                "operator": ">",
                "right_kind": "value",
                "right_value": 10.4,
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            rules_path = tmp_path / "entry.json"
            out_dir = tmp_path / "out"
            rules_path.write_text(json.dumps(rules), encoding="utf-8")

            rc = main(
                [
                    "--ticker", "TEST3",
                    "--period", "1y",
                    "--timeframe", "Diário",
                    "--entry-rules", str(rules_path),
                    "--capital", "10000",
                    "--output-dir", str(out_dir),
                ],
                provider=FakeProvider(),
            )

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "metrics.json").exists())
            self.assertTrue((out_dir / "trades.csv").exists())
            self.assertTrue((out_dir / "equity.csv").exists())

            payload = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["ticker"], "TEST3")
            self.assertEqual(payload["bars"], 8)
            self.assertEqual(payload["mode"], "rules")
            self.assertGreaterEqual(payload["metrics"]["trades"], 1)

    def test_cli_setup_mode_writes_orders_and_runs_trigger_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "setup-out"
            rc = main(
                [
                    "--ticker", "TEST3",
                    "--period", "1y",
                    "--timeframe", "Diário",
                    "--setup", "pfr_buy",
                    "--capital", "10000",
                    "--output-dir", str(out_dir),
                ],
                provider=SetupProvider(),
            )

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "orders.csv").exists())
            payload = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "setup")
            self.assertEqual(payload["setup"], "pfr_buy")
            self.assertGreaterEqual(payload["orders"], 1)
            self.assertGreaterEqual(payload["metrics"]["trades"], 1)


if __name__ == "__main__":
    unittest.main()
