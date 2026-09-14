import unittest

import numpy as np
import pandas as pd

from eod_checklist import (
    _completed_resample,
    _landry_classic_state,
    evaluate_eod_latest,
)


def _frame(rows: int = 260) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=rows)
    base = np.linspace(20.0, 50.0, rows)
    return pd.DataFrame(
        {
            "Open": base - 0.10,
            "High": base + 0.40,
            "Low": base - 0.40,
            "Close": base,
            "Volume": np.full(rows, 1_000_000.0),
        },
        index=index,
    )


class ChecklistEODTests(unittest.TestCase):
    def test_score_is_bounded_and_has_required_fields(self):
        daily = _frame()
        weekly = _completed_resample(daily, "Semanal")
        row = evaluate_eod_latest("TEST3", daily, weekly, "Diário")
        self.assertGreaterEqual(row["Nota"], 0)
        self.assertLessEqual(row["Nota"], 9)
        self.assertIn(row["Prioridade"], {"A", "B", "C"})
        self.assertIn("Setups", row)
        self.assertIn("Tendência maior", row)

    def test_partial_week_is_removed(self):
        index = pd.bdate_range("2026-09-07", periods=6)
        frame = pd.DataFrame(
            {
                "Open": range(6),
                "High": [x + 1 for x in range(6)],
                "Low": [x - 1 for x in range(6)],
                "Close": range(6),
                "Volume": [100] * 6,
            },
            index=index,
        )
        weekly = _completed_resample(frame, "Semanal")
        self.assertLessEqual(pd.Timestamp(weekly.index.max()).normalize(), pd.Timestamp(frame.index.max()).normalize())

    def test_landry_classic_detects_three_lower_highs(self):
        frame = _frame(120)
        anchor = len(frame) - 4

        frame.iloc[anchor, frame.columns.get_loc("High")] = 60.0
        frame.iloc[anchor, frame.columns.get_loc("Close")] = 59.0
        frame.iloc[anchor, frame.columns.get_loc("Open")] = 58.5
        frame.iloc[anchor, frame.columns.get_loc("Low")] = 58.0

        highs = [58.0, 57.0, 56.0]
        lows = [56.0, 55.0, 54.0]
        closes = [57.0, 56.0, 55.0]
        for offset, (high, low, close) in enumerate(zip(highs, lows, closes), start=1):
            i = anchor + offset
            frame.iloc[i, frame.columns.get_loc("High")] = high
            frame.iloc[i, frame.columns.get_loc("Low")] = low
            frame.iloc[i, frame.columns.get_loc("Close")] = close
            frame.iloc[i, frame.columns.get_loc("Open")] = close + 0.1

        state = _landry_classic_state(frame)
        self.assertIsNotNone(state)
        self.assertEqual(state.name, "Dave Landry")
        self.assertEqual(state.strength, 2)


if __name__ == "__main__":
    unittest.main()
