import unittest
from datetime import date

from yahoo_audit import (
    EndpointResult,
    chart_url,
    diagnose_ticker,
    normalize_tickers,
    parse_chart_payload,
)


class YahooAuditTests(unittest.TestCase):
    def test_normalize_tickers(self):
        self.assertEqual(
            normalize_tickers("PETR4.SA, vale3; ITUB4\nPETR4"),
            ["PETR4", "VALE3", "ITUB4"],
        )

    def test_chart_url_exposes_exact_endpoint(self):
        url = chart_url("PETR4", period="1mo")
        self.assertIn("query2.finance.yahoo.com/v8/finance/chart/PETR4.SA", url)
        self.assertIn("range=1mo", url)
        self.assertIn("interval=1d", url)

    def test_parse_chart_payload(self):
        payload = {
            "chart": {
                "error": None,
                "result": [{
                    "timestamp": [1789743600, 1789830000],
                    "meta": {"exchangeName": "SAO"},
                }],
            }
        }
        latest, rows, meta, error = parse_chart_payload(payload)
        self.assertIsNone(error)
        self.assertEqual(rows, 2)
        self.assertEqual(meta["exchangeName"], "SAO")
        self.assertIsNotNone(latest)

    def test_diagnoses_batch_divergence(self):
        expected = date(2026, 9, 18)
        individual = {"latest_date": expected}
        batch = {"latest_date": date(2026, 9, 16)}
        endpoints = [
            EndpointResult("query1", "u1", 200, expected, 20, None, {}),
            EndpointResult("query2", "u2", 200, expected, 20, None, {}),
        ]
        diagnosis = diagnose_ticker(expected, individual, batch, endpoints)
        self.assertIn("lote", diagnosis.lower())

    def test_diagnoses_yfinance_lag_when_direct_endpoint_is_current(self):
        expected = date(2026, 9, 18)
        individual = {"latest_date": date(2026, 9, 16)}
        batch = {"latest_date": date(2026, 9, 16)}
        endpoints = [
            EndpointResult("query1", "u1", 200, expected, 20, None, {}),
            EndpointResult("query2", "u2", 200, expected, 20, None, {}),
        ]
        diagnosis = diagnose_ticker(expected, individual, batch, endpoints)
        self.assertIn("endpoint direto", diagnosis.lower())
        self.assertIn("yfinance", diagnosis.lower())


if __name__ == "__main__":
    unittest.main()
