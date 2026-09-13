import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class NavigationSmokeTest(unittest.TestCase):
    def test_router_renders_screener_without_exceptions(self):
        app = AppTest.from_file("app.py", default_timeout=15)
        app.run()
        self.assertEqual(len(app.exception), 0, [str(exc) for exc in app.exception])
        self.assertGreaterEqual(len(app.title), 1)
        self.assertIn("B3 Strategy Builder", app.title[0].value)

    def test_navigation_uses_expected_labels(self):
        source = Path("app.py").read_text(encoding="utf-8")
        self.assertIn('title="Screener"', source)
        self.assertIn('title="Backtesting"', source)
        self.assertIn('default=True', source)


if __name__ == "__main__":
    unittest.main()
