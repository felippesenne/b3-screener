import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import requests

from data_provider import BrapiProvider, ResilientMarketDataProvider, YahooFinanceProvider, normalize_ohlcv
from market_sessions import MARKET_TZ, expected_latest_closed_session
from scanner import scan_universe

NOW = datetime(2026, 9, 20, 12, tzinfo=MARKET_TZ)


def candles(end="2026-09-18", start="2026-08-03"):
    index = pd.bdate_range(start, end)
    return pd.DataFrame({"Open": 10., "High": 12., "Low": 9., "Close": 11., "Volume": 1000.}, index=index)


def source(frames=None, errors=None):
    provider = Mock()
    provider.get_histories.return_value = (frames or {}, errors or {})
    return provider


def payload(symbol="PETR4", used_range="1mo", used_interval="1d"):
    return {"results": [{"requestedSymbol": symbol, "symbol": symbol, "data": {
        "usedRange": used_range, "usedInterval": used_interval,
        "historicalDataPrice": [
            {"date": int(pd.Timestamp(day, tz=MARKET_TZ).timestamp()), "open": 10, "high": 12,
             "low": 9, "close": 11, "volume": 100, "adjustedClose": 8}
            for day in ["2026-09-18", "2026-09-17"]
        ]}}]}


def session_with(data=None, status=200):
    response = Mock(status_code=status)
    response.json.return_value = data or payload()
    session = Mock()
    session.get.return_value = response
    return session


class ProviderTests(unittest.TestCase):
    def test_primary_first_fallback_only_failed_and_stale_symbols(self):
        primary = source({"PETR4": candles(), "VALE3": candles("2026-09-17")}, {"BBAS3": "HTTP 429"})
        fallback = source({"VALE3": candles(), "BBAS3": candles()})
        provider = ResilientMarketDataProvider(primary=primary, fallback=fallback, now=NOW)
        frames, errors = provider.get_histories(["PETR4", "VALE3", "BBAS3", "PETR4"], "1mo")
        self.assertFalse(errors)
        self.assertEqual(set(frames), {"PETR4", "VALE3", "BBAS3"})
        self.assertEqual(fallback.get_histories.call_args.args[0], ["VALE3", "BBAS3"])
        self.assertEqual(frames["PETR4"].attrs["source"], "brapi")
        self.assertEqual(frames["VALE3"].attrs["source"], "Yahoo Finance")
        self.assertIn("defasados", provider.diagnostics["VALE3"]["attempts"][0]["error"])

    def test_healthy_primary_never_calls_yahoo(self):
        fallback = source()
        provider = ResilientMarketDataProvider(primary=source({"PETR4": candles()}), fallback=fallback, now=NOW)
        provider.get_history("PETR4", "1mo")
        fallback.get_histories.assert_not_called()

    def test_stale_data_never_reaches_signal_evaluation(self):
        provider = ResilientMarketDataProvider(
            primary=source({"PETR4": candles("2026-09-17")}),
            fallback=source({"PETR4": candles("2026-09-16")}), now=NOW)
        with patch("scanner.evaluate_latest") as evaluate:
            result, errors = scan_universe(["PETR4"], provider, "Diário", "1mo", [])
        self.assertTrue(result.empty)
        self.assertIn("18/09/2026", errors["PETR4"])
        self.assertEqual(provider.diagnostics["PETR4"]["latest_date"].isoformat(), "2026-09-17")
        self.assertEqual(provider.diagnostics["PETR4"]["status"], "Defasado")
        evaluate.assert_not_called()

    def test_all_failures_are_returned_without_per_symbol_retry(self):
        primary, fallback = source(errors={"PETR4": "HTTP 429"}), source(errors={"PETR4": "HTTP 429"})
        provider = ResilientMarketDataProvider(primary=primary, fallback=fallback, now=NOW)
        _, errors = provider.get_histories(["PETR4"], "1mo")
        self.assertIn("brapi", errors["PETR4"])
        self.assertIn("Yahoo", errors["PETR4"])
        self.assertEqual(primary.get_histories.call_count, 1)
        self.assertEqual(fallback.get_histories.call_count, 1)

    def test_today_candle_is_excluded_before_cutoff(self):
        now = datetime(2026, 9, 18, 17, tzinfo=MARKET_TZ)
        provider = ResilientMarketDataProvider(primary=source({"PETR4": candles()}), fallback=source(), now=now)
        frame = provider.get_history("PETR4", "1mo")
        self.assertEqual(frame.index[-1].date().isoformat(), "2026-09-17")

    def test_incomplete_primary_uses_complete_fallback_without_splicing(self):
        short = candles(start="2026-09-15")
        fallback_frame = candles()
        fallback_frame["Close"] = 10.5
        provider = ResilientMarketDataProvider(primary=source({"PETR4": short}), fallback=source({"PETR4": fallback_frame}), now=NOW)
        frame = provider.get_history("PETR4", "1mo")
        self.assertTrue((frame["Close"] == 10.5).all())
        self.assertEqual(frame.attrs["source"], "Yahoo Finance")

    def test_invalid_latest_candle_triggers_fallback(self):
        bad = candles()
        bad.loc[bad.index[-1], "Open"] = np.nan
        provider = ResilientMarketDataProvider(primary=source({"PETR4": bad}), fallback=source({"PETR4": candles()}), now=NOW)
        self.assertEqual(provider.get_history("PETR4", "1mo").attrs["source"], "Yahoo Finance")

    def test_source_and_daily_date_survive_weekly_aggregation(self):
        provider = ResilientMarketDataProvider(primary=source({"PETR4": candles()}), fallback=source(), now=NOW)
        result, errors = scan_universe(["PETR4"], provider, "Semanal", "1mo", [])
        self.assertFalse(errors)
        self.assertEqual(result.iloc[0]["Fonte"], "brapi")
        self.assertEqual(result.iloc[0]["Último pregão"], "18/09/2026")


class YahooBatchTests(unittest.TestCase):
    def test_single_fallback_symbol_handles_both_multiindex_orders(self):
        base = candles()
        for ticker_first in (True, False):
            downloaded = pd.concat({"PETR4.SA": base}, axis=1)
            if not ticker_first:
                downloaded = downloaded.swaplevel(axis=1)
            with patch("data_provider.yf.download", return_value=downloaded):
                frames, errors = YahooFinanceProvider().get_histories(["PETR4"], "1mo")
            self.assertFalse(errors)
            pd.testing.assert_frame_equal(frames["PETR4"], base)


class BrapiTests(unittest.TestCase):
    def test_v2_schema_dates_order_ohlc_and_header_auth(self):
        session = session_with()
        frame = BrapiProvider("secret-test-token", session).get_history("petr4.sa", "1mo")
        self.assertEqual(frame.index[-1].date().isoformat(), "2026-09-18")
        self.assertTrue(frame.index.is_monotonic_increasing)
        self.assertEqual(frame.iloc[-1]["Close"], 11)
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-test-token")
        self.assertNotIn("token", kwargs["params"])
        self.assertEqual(kwargs["params"]["interval"], "1d")

    def test_missing_token_skips_non_demo_without_http(self):
        session = session_with()
        provider = BrapiProvider("", session)
        with self.assertRaisesRegex(ValueError, "Token brapi necessário"):
            provider.get_history("BBAS3")
        session.get.assert_not_called()

    def test_rate_limit_stops_additional_requests(self):
        for status in (401, 403, 429, 503):
            session = session_with(status=status)
            provider = BrapiProvider("secret-test-token", session)
            frames, errors = provider.get_histories(["PETR4", "VALE3", "BBAS3"])
            self.assertFalse(frames)
            self.assertEqual(len(errors), 3)
            self.assertEqual(session.get.call_count, 1)
            self.assertNotIn("secret-test-token", str(errors))

    def test_transport_errors_do_not_leak_credentials(self):
        session = session_with()
        session.get.side_effect = requests.Timeout("secret-test-token")
        with self.assertRaisesRegex(ValueError, "tempo limite") as caught:
            BrapiProvider("secret-test-token", session).get_history("PETR4")
        self.assertNotIn("secret-test-token", str(caught.exception))

    def test_silent_plan_truncation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "limitou o histórico"):
            BrapiProvider("", session_with()).get_history("PETR4", "2y")

    def test_wrong_symbol_or_interval_is_rejected(self):
        for data in (payload(symbol="VALE3"), payload(used_interval="1wk")):
            with self.assertRaises(ValueError):
                BrapiProvider("", session_with(data)).get_history("PETR4", "1mo")

    def test_invalid_ohlcv_is_rejected(self):
        for column, value in [("Open", np.nan), ("High", 8), ("Volume", -1), ("Close", np.inf)]:
            frame = candles()
            frame.loc[frame.index[-1], column] = value
            with self.assertRaises(ValueError):
                normalize_ohlcv(frame)
        with self.assertRaisesRegex(ValueError, "duplicados"):
            normalize_ohlcv(pd.concat([candles(), candles().tail(1)]))


class CalendarTests(unittest.TestCase):
    def test_closed_sessions_include_holidays_weekends_and_timezone(self):
        cases = [
            ("2026-09-20T12:00:00-03:00", "2026-09-18"),
            ("2026-09-21T08:00:00-03:00", "2026-09-18"),
            ("2026-09-18T18:29:00-03:00", "2026-09-17"),
            ("2026-09-18T18:30:00-03:00", "2026-09-18"),
            ("2026-09-07T19:00:00-03:00", "2026-09-04"),
            ("2026-02-17T19:00:00-03:00", "2026-02-13"),
            ("2026-04-03T19:00:00-03:00", "2026-04-02"),
            ("2026-12-25T19:00:00-03:00", "2026-12-23"),
            ("2026-09-18T21:29:00+00:00", "2026-09-17"),
        ]
        for timestamp, expected in cases:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(expected_latest_closed_session(datetime.fromisoformat(timestamp)).isoformat(), expected)


if __name__ == "__main__":
    unittest.main()
