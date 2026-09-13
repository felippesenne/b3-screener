from __future__ import annotations

from datetime import date

import pandas as pd

from portfolio.calculations import (
    build_asset_summary,
    build_options_view,
    build_sheet_view,
    build_stocks_view,
    portfolio_totals,
)


def sample_data():
    stocks = pd.DataFrame([
        {"Ativo": "BBAS3", "Quantidade": 1000, "Preço médio": 20.0, "Cotação manual": None},
    ])
    options = pd.DataFrame([
        {
            "Opção": "BBASA_TEST",
            "Ativo base": "BBAS3",
            "Tipo": "CALL",
            "Operação": "VENDA",
            "Quantidade": 1000,
            "Preço médio": 0.50,
            "Strike": 22.0,
            "Vencimento": "2026-12-18",
            "Status": "ABERTA",
            "Preço encerramento": None,
            "Preço atual manual": None,
            "Delta manual": None,
        },
        {
            "Opção": "BBASM_TEST",
            "Ativo base": "BBAS3",
            "Tipo": "PUT",
            "Operação": "VENDA",
            "Quantidade": 500,
            "Preço médio": 0.80,
            "Strike": 18.0,
            "Vencimento": "2026-12-18",
            "Status": "ENCERRADA",
            "Preço encerramento": 0.30,
            "Preço atual manual": None,
            "Delta manual": None,
        },
    ])
    analytics = {
        "BBASA_TEST": {
            "symbol": "BBASA_TEST",
            "underlyingSymbol": "BBAS3",
            "side": "call",
            "strike": 22.0,
            "expirationDate": "2026-12-18",
            "underlyingPrice": 21.0,
            "optionPrice": 0.30,
            "delta": 0.35,
            "gamma": 0.04,
            "theta": -0.02,
            "vega": 0.08,
            "impliedVolatility": 0.30,
            "openInterest": 10000,
            "priceSource": "close",
            "confidence": "high",
            "date": "2026-09-11",
        }
    }
    return stocks, options, analytics


def test_stock_and_option_mark_to_market():
    stocks, options, analytics = sample_data()
    stocks_view = build_stocks_view(stocks, {"BBAS3": 21.0})
    options_view = build_options_view(options, analytics, {"BBAS3": 21.0}, today=date(2026, 9, 13))

    assert round(float(stocks_view.loc[0, "P/L ações"]), 2) == 1000.00
    call = options_view[options_view["Opção"] == "BBASA_TEST"].iloc[0]
    assert round(float(call["P/L MTM"]), 2) == 200.00
    assert round(float(call["Prêmio inicial"]), 2) == 500.00
    assert round(float(call["Delta equivalente"]), 2) == -350.00
    assert call["Moneyness"] == "OTM"

    put = options_view[options_view["Opção"] == "BBASM_TEST"].iloc[0]
    assert round(float(put["P/L realizado"]), 2) == 250.00


def test_summary_and_total_delta():
    stocks, options, analytics = sample_data()
    stocks_view = build_stocks_view(stocks, {"BBAS3": 21.0})
    options_view = build_options_view(options, analytics, {"BBAS3": 21.0}, today=date(2026, 9, 13))
    summary = build_asset_summary(stocks_view, options_view)
    totals = portfolio_totals(stocks_view, options_view)

    row = summary.iloc[0]
    assert round(float(row["Delta líquido (ações eq.)"]), 2) == 650.00
    assert round(float(row["Cobertura calls %"]), 2) == 100.00
    assert round(float(totals["net_pnl"]), 2) == 1450.00
    assert round(float(totals["net_delta_equiv"]), 2) == 650.00


def test_sheet_view_reproduces_covered_call_logic():
    stocks, options, analytics = sample_data()
    stocks_view = build_stocks_view(stocks, {"BBAS3": 21.0})
    options_view = build_options_view(options, analytics, {"BBAS3": 21.0}, today=date(2026, 9, 13))
    sheet = build_sheet_view(stocks_view, options_view)
    call = sheet[sheet["Opção"] == "BBASA_TEST"].iloc[0]

    assert round(float(call["Diferença"]), 2) == 2.00
    assert round(float(call["Saldo no exercício"]), 2) == 2000.00
    assert round(float(call["Prêmio inicial"]), 2) == 500.00
    assert round(float(call["TOTAL potencial/histórico"]), 2) == 2500.00


if __name__ == "__main__":
    test_stock_and_option_mark_to_market()
    test_summary_and_total_delta()
    test_sheet_view_reproduces_covered_call_logic()
    print("portfolio tests: ok")
