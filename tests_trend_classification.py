from scanner import trend_label


def test_trend_labels():
    cases = [
        ((19.9, 30, 10), "🟡 Lateral"),
        ((22.0, 30, 10), "🟠 Transição ↑"),
        ((22.0, 10, 30), "🟠 Transição ↓"),
        ((25.0, 30, 10), "🟢 Alta"),
        ((34.9, 10, 30), "🔴 Baixa"),
        ((35.0, 30, 10), "🟢 Alta forte"),
        ((50.0, 10, 30), "🔴 Baixa forte"),
        ((40.0, 20, 20), "🟡 Lateral"),
        ((float("nan"), 30, 10), "⚪ Sem dados"),
    ]

    for values, expected in cases:
        actual = trend_label(*values)
        assert actual == expected, (values, actual, expected)


if __name__ == "__main__":
    test_trend_labels()
    print("trend classification: ok")
