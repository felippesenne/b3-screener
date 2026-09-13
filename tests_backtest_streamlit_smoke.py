import unittest

from streamlit.testing.v1 import AppTest


class BacktestingPageSmokeTest(unittest.TestCase):
    def test_backtesting_page_renders_without_exceptions(self):
        app = AppTest.from_file("pages/1_Backtesting.py", default_timeout=15)
        app.run()
        self.assertEqual(len(app.exception), 0, [str(exc) for exc in app.exception])
        self.assertGreaterEqual(len(app.title), 1)
        self.assertIn("B3 Backtesting Lab", app.title[0].value)
        self.assertGreaterEqual(len(app.button), 1)
        self.assertTrue(any(button.label == "Executar backtest" for button in app.button))


if __name__ == "__main__":
    unittest.main()
