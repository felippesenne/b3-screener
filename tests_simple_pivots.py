import pandas as pd

from trade_de_valor_setups import trade_de_valor_setup_state


def _df(rows):
    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="D"))


def test_simple_pivot_buy_confirmed():
    df = _df([
        {"Open": 10.0, "High": 10.8, "Low": 9.8, "Close": 10.2, "Volume": 1},
        {"Open": 9.5, "High": 10.0, "Low": 9.0, "Close": 9.6, "Volume": 1},
        {"Open": 10.2, "High": 11.2, "Low": 10.0, "Close": 10.8, "Volume": 1},
        {"Open": 12.0, "High": 13.0, "Low": 11.0, "Close": 12.6, "Volume": 1},
        {"Open": 10.8, "High": 12.0, "Low": 10.0, "Close": 10.7, "Volume": 1},
        {"Open": 11.5, "High": 12.5, "Low": 10.8, "Close": 12.0, "Volume": 1},
        {"Open": 12.8, "High": 13.5, "Low": 12.0, "Close": 13.2, "Volume": 1},
        {"Open": 13.2, "High": 14.0, "Low": 12.7, "Close": 13.8, "Volume": 1},
    ])
    state = trade_de_valor_setup_state(df, "simple_pivot_buy")
    assert state["passed"] is True
    assert "CONFIRMADO" in state["status"]
    assert state["entry"] == 13.0
    assert state["stop"] == 10.0


def test_simple_pivot_sell_confirmed():
    df = _df([
        {"Open": 10.0, "High": 10.2, "Low": 9.2, "Close": 9.7, "Volume": 1},
        {"Open": 10.5, "High": 11.0, "Low": 10.0, "Close": 10.4, "Volume": 1},
        {"Open": 10.2, "High": 10.5, "Low": 9.2, "Close": 9.6, "Volume": 1},
        {"Open": 9.0, "High": 9.5, "Low": 8.0, "Close": 8.4, "Volume": 1},
        {"Open": 9.4, "High": 10.0, "Low": 8.8, "Close": 9.6, "Volume": 1},
        {"Open": 9.0, "High": 9.3, "Low": 8.5, "Close": 8.8, "Volume": 1},
        {"Open": 8.2, "High": 8.6, "Low": 7.7, "Close": 7.9, "Volume": 1},
        {"Open": 7.9, "High": 8.1, "Low": 7.2, "Close": 7.5, "Volume": 1},
    ])
    state = trade_de_valor_setup_state(df, "simple_pivot_sell")
    assert state["passed"] is True
    assert "CONFIRMADO" in state["status"]
