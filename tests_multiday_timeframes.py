import unittest

import pandas as pd

from indicators import resample_ohlcv


class MultiDayTimeframeTests(unittest.TestCase):
    def setUp(self):
        dates = pd.to_datetime(
            [
                "2026-09-14",
                "2026-09-15",
                "2026-09-16",
                "2026-09-17",
                "2026-09-18",
                "2026-09-21",  # segunda-feira: fim de semana não cria candles
                "2026-09-22",
                "2026-09-23",
                "2026-09-24",
                "2026-09-25",
            ]
        )
        values = list(range(1, 11))
        self.df = pd.DataFrame(
            {
                "Open": values,
                "High": [value + 0.5 for value in values],
                "Low": [value - 0.5 for value in values],
                "Close": [value + 0.25 for value in values],
                "Volume": [value * 100 for value in values],
            },
            index=dates,
        )

    def test_two_day_bars_count_trading_sessions_not_calendar_days(self):
        out = resample_ohlcv(self.df, "2 dias")

        self.assertEqual(
            list(out.index.strftime("%Y-%m-%d")),
            ["2026-09-15", "2026-09-17", "2026-09-21", "2026-09-23", "2026-09-25"],
        )
        # 18/09 (sexta) + 21/09 (segunda) pertencem ao mesmo candle 2D.
        weekend_bar = out.loc[pd.Timestamp("2026-09-21")]
        self.assertEqual(float(weekend_bar["Open"]), 5.0)
        self.assertEqual(float(weekend_bar["High"]), 6.5)
        self.assertEqual(float(weekend_bar["Low"]), 4.5)
        self.assertEqual(float(weekend_bar["Close"]), 6.25)
        self.assertEqual(float(weekend_bar["Volume"]), 1100.0)

    def test_three_day_bars_keep_current_partial_block(self):
        out = resample_ohlcv(self.df, "3 dias")

        self.assertEqual(
            list(out.index.strftime("%Y-%m-%d")),
            ["2026-09-16", "2026-09-21", "2026-09-24", "2026-09-25"],
        )
        # O último candle ainda está em formação e contém apenas o pregão de 25/09.
        partial = out.iloc[-1]
        self.assertEqual(float(partial["Open"]), 10.0)
        self.assertEqual(float(partial["High"]), 10.5)
        self.assertEqual(float(partial["Low"]), 9.5)
        self.assertEqual(float(partial["Close"]), 10.25)
        self.assertEqual(float(partial["Volume"]), 1000.0)

    def test_alignment_does_not_shift_when_history_window_changes(self):
        full = resample_ohlcv(self.df, "2 dias")
        shorter = resample_ohlcv(self.df.loc["2026-09-16":], "2 dias")

        expected_dates = ["2026-09-17", "2026-09-21", "2026-09-23", "2026-09-25"]
        self.assertEqual(list(shorter.index.strftime("%Y-%m-%d")), expected_dates)
        pd.testing.assert_frame_equal(full.loc[shorter.index], shorter)


if __name__ == "__main__":
    unittest.main()
