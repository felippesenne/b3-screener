import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from data_provider import ResilientMarketDataProvider
from tests_market_data import NOW, candles, source


class MarketDataUITests(unittest.TestCase):
    def test_screener_renders_data_audit_and_blocks_stale_symbols(self):
        provider = ResilientMarketDataProvider(
            primary=source({"PETR4": candles(start="2024-09-18"), "VALE3": candles("2026-09-17", "2024-09-18")}),
            fallback=source(errors={"VALE3": "HTTP 429"}), now=NOW)
        with patch("data_provider.ResilientMarketDataProvider", return_value=provider):
            app = AppTest.from_file("pages/Screener.py", default_timeout=15).run()
            app.text_area(key="ticker_text").set_value("PETR4\nVALE3").run()
            next(button for button in app.button if button.label == "Rodar screener").click().run()
        self.assertFalse(app.exception, [str(e) for e in app.exception])
        self.assertTrue(any("1 de 2 ativos excluídos" in warning.value for warning in app.warning))
        audit = next(table.value for table in app.dataframe if "Situação dos dados" in table.value.columns)
        self.assertEqual(audit.set_index("Ticker").loc["VALE3", "Situação dos dados"], "Defasado")
        self.assertEqual(audit.set_index("Ticker").loc["PETR4", "Fonte"], "brapi")

    def test_checklist_renders_with_configuration_and_no_initial_network(self):
        with patch("data_provider.BrapiProvider.get_histories") as brapi, patch("data_provider.YahooFinanceProvider.get_histories") as yahoo:
            app = AppTest.from_file("pages/3_Checklist_EOD.py", default_timeout=15).run()
        self.assertFalse(app.exception, [str(e) for e in app.exception])
        self.assertTrue(any("Sem token" in item.value for item in app.warning))
        brapi.assert_not_called()
        yahoo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
