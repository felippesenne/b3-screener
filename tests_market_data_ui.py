import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests_market_data import candles, source


class MarketDataUITests(unittest.TestCase):
    def test_screener_uses_yahoo_only_and_renders_without_brapi_audit(self):
        provider = source({
            "PETR4": candles(start="2024-09-18"),
            "VALE3": candles(start="2024-09-18"),
            "ITUB4": candles(start="2024-09-18"),
        })
        with patch("data_provider.YahooFinanceProvider", return_value=provider):
            app = AppTest.from_file("pages/Screener.py", default_timeout=15).run()
            app.text_area(key="ticker_text").set_value("PETR4\nVALE3").run()
            next(button for button in app.button if button.label == "Rodar screener").click().run()

        self.assertFalse(app.exception, [str(e) for e in app.exception])
        self.assertGreaterEqual(provider.get_histories.call_count, 2)
        self.assertTrue(any("Yahoo Finance via yfinance" in item.value for item in app.caption))
        self.assertFalse(
            any("Situação dos dados" in table.value.columns for table in app.dataframe),
            "O Screener Yahoo-only não deve renderizar a auditoria específica da brapi/fallback.",
        )

    def test_checklist_renders_with_configuration_and_no_initial_network(self):
        with patch("data_provider.BrapiProvider.get_histories") as brapi, patch("data_provider.YahooFinanceProvider.get_histories") as yahoo:
            app = AppTest.from_file("pages/3_Checklist_EOD.py", default_timeout=15).run()
        self.assertFalse(app.exception, [str(e) for e in app.exception])
        self.assertTrue(any("Sem token" in item.value for item in app.warning))
        brapi.assert_not_called()
        yahoo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
