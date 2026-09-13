import math

import pandas as pd

from classic_setups import SPECIAL_SETUP_OPS
from momentum_205080_setups import momentum_205080_state


def _trend_frame(side: str) -> pd.DataFrame:
    rows = []
    for i in range(120):
        drift = 20.0 + 0.08 * i if side == "buy" else 40.0 - 0.08 * i
        wave = 0.35 * math.sin(i * math.pi / 4.0)
        close = drift + wave
        rows.append(
            {
                "Open": close - 0.05 if side == "buy" else close + 0.05,
                "High": close + 0.15,
                "Low": close - 0.15,
                "Close": close,
                "Volume": 1_000_000,
            }
        )

    if side == "buy":
        rows[118].update({"Open": 28.90, "High": 29.25, "Low": 28.55, "Close": 29.00})
        rows[119].update({"Open": 29.10, "High": 29.60, "Low": 29.05, "Close": 29.45})
    else:
        rows[118].update({"Open": 31.10, "High": 31.45, "Low": 30.75, "Close": 31.00})
        rows[119].update({"Open": 30.90, "High": 30.95, "Low": 30.40, "Close": 30.55})

    return pd.DataFrame(rows, index=pd.date_range("2026-01-01", periods=len(rows), freq="B"))


def test_registry():
    assert "momentum_205080_buy" in SPECIAL_SETUP_OPS
    assert "momentum_205080_sell" in SPECIAL_SETUP_OPS


def test_buy():
    state = momentum_205080_state(_trend_frame("buy"), "momentum_205080_buy")
    assert state["passed"] is True, state
    assert state["direction"] == "Compra"
    assert state["entry"] is not None
    assert state["stop"] is not None
    assert state["target_2r"] > state["entry"]
    assert "CONFIRMADO" in state["status"] or "ARMADO" in state["status"]


def test_sell():
    state = momentum_205080_state(_trend_frame("sell"), "momentum_205080_sell")
    assert state["passed"] is True, state
    assert state["direction"] == "Venda"
    assert state["entry"] is not None
    assert state["stop"] is not None
    assert state["target_2r"] < state["entry"]
    assert "CONFIRMADO" in state["status"] or "ARMADO" in state["status"]


def run_all():
    for test in (test_registry, test_buy, test_sell):
        test()
        print("PASS", test.__name__)


if __name__ == "__main__":
    run_all()
