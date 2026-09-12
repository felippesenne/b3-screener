import pandas as pd

from classic_setups import SPECIAL_SETUP_OPS
from structure_setups import structure_setup_state


def _frame(highs, lows, closes=None):
    if closes is None:
        closes = [(h + l) / 2.0 for h, l in zip(highs, lows)]
    opens = list(closes)
    return pd.DataFrame(
        {
            "Open": opens,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": [1_000_000] * len(highs),
        },
        index=pd.date_range("2026-01-01", periods=len(highs), freq="D"),
    )


def test_registry():
    required = {
        "pivot_123_buy", "pivot_123_sell", "hns_buy", "hns_sell",
        "double_bottom", "double_top",
        "divergence_structure_buy", "divergence_structure_sell",
        "setup_91_structure_buy", "setup_91_structure_sell",
    }
    assert required <= SPECIAL_SETUP_OPS


def test_pivot_123_buy():
    df = _frame(
        [11, 10.5, 10, 11, 12, 11, 10.5, 11, 11.5],
        [10, 9.5, 8, 9, 10, 9.5, 9, 9.5, 10],
    )
    state = structure_setup_state(df, "pivot_123_buy")
    assert state["passed"] is True, state
    assert state["entry"] == 12
    assert state["stop"] == 9


def test_double_bottom():
    df = _frame(
        [11, 10.5, 10, 11, 12, 11, 10.7, 11, 11.5],
        [10, 9.5, 8.0, 9.0, 10.0, 9.4, 8.1, 9.3, 9.8],
    )
    state = structure_setup_state(df, "double_bottom")
    assert state["passed"] is True, state
    assert state["entry"] == 12


def test_double_top():
    df = _frame(
        [10, 10.5, 12.0, 11.0, 10.0, 11.0, 12.1, 11.0, 10.8],
        [9, 9.5, 10.5, 9.5, 8.0, 9.2, 10.4, 9.6, 9.4],
    )
    state = structure_setup_state(df, "double_top")
    assert state["passed"] is True, state
    assert state["entry"] == 8.0


def test_oco_sell():
    df = _frame(
        [11, 12, 11.5, 11, 12, 14, 12, 11, 11.8, 12.2, 11.8],
        [10.5, 11, 10.5, 10, 10.8, 12, 10.8, 10.2, 10.8, 11, 10.8],
    )
    state = structure_setup_state(df, "hns_sell")
    assert state["passed"] is True, state
    assert state["entry"] == 10.0


def test_oco_inverse_buy():
    df = _frame(
        [11, 10.5, 11, 12, 11, 9, 11, 12.1, 11.2, 10.8, 11.5],
        [10.5, 10, 10.5, 11, 10, 8, 10, 11, 10.5, 10.2, 10.5],
    )
    state = structure_setup_state(df, "hns_buy")
    assert state["passed"] is True, state
    assert state["entry"] == 12.1


def test_bullish_divergence_with_structure():
    closes = [
        20, 19.5, 19, 18.5, 18, 17.5, 17, 16.5, 16, 15.5,
        15, 14.5, 14, 13.5, 13, 12.5, 12, 11.5, 11, 10,
        11, 12, 13, 14, 13.5, 13, 12.5, 12, 11.5, 11,
        10.5, 10.2, 10.0, 9.8, 10.5,
    ]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    df = _frame(highs, lows, closes)
    state = structure_setup_state(df, "divergence_structure_buy")
    assert state["passed"] is True, state
    assert "IFR14" in state["status"]


def test_91_plus_structure_buy():
    closes = [15, 14.5, 14, 13.5, 13, 12.5, 12, 11.5, 11, 10,
              10.5, 11, 11.5, 12, 11.5, 11, 10.8, 11.2, 11.6]
    highs = [c + 0.2 for c in closes]
    lows = [c - 0.2 for c in closes]
    df = _frame(highs, lows, closes)
    state = structure_setup_state(df, "setup_91_structure_buy")
    assert state["passed"] is True, state
    assert "9.1" in state["name"]


def run_all():
    tests = [
        test_registry,
        test_pivot_123_buy,
        test_double_bottom,
        test_double_top,
        test_oco_sell,
        test_oco_inverse_buy,
        test_bullish_divergence_with_structure,
        test_91_plus_structure_buy,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)


if __name__ == "__main__":
    run_all()
