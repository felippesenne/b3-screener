import unittest

from streamlit.testing.v1 import AppTest


class PortfolioPageSmokeTest(unittest.TestCase):
    def test_portfolio_page_renders_without_exceptions(self):
        app = AppTest.from_file("pages/2_Carteira.py", default_timeout=20)
        app.run()
        self.assertEqual(len(app.exception), 0, [str(exc) for exc in app.exception])
        self.assertGreaterEqual(len(app.title), 1)
        self.assertIn("Carteira", app.title[0].value)


if __name__ == "__main__":
    unittest.main()
