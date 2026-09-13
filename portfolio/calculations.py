from __future__ import annotations

from datetime import date
import math

import numpy as np
import pandas as pd


STOCK_INPUT_COLUMNS = ["Ativo", "Quantidade", "Preço médio", "Cotação manual"]
OPTION_INPUT_COLUMNS = [
    "Opção",
    "Ativo base",
    "Tipo",
    "Operação",
    "Quantidade",
    "Preço médio",
    "Strike",
    "Vencimento",
    "Status",
    "Preço encerramento",
    "Preço atual manual",
    "Delta manual",
]


def _num(value, default: float = float("nan")) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _text(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def _upper(value) -> str:
    return _text(value).upper()


def _option_sign(operation: str) -> float:
    return -1.0 if _upper(operation).startswith("VEND") else 1.0


def _is_open(status: str) -> bool:
    return not _upper(status).startswith("ENCERR")


def _coerce_date(value):
    if value is None or _text(value) == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _moneyness(option_type: str, underlying: float, strike: float) -> str:
    if not math.isfinite(underlying) or not math.isfinite(strike) or underlying <= 0:
        return "—"
    distance = (underlying - strike) / underlying
    if abs(distance) <= 0.01:
        return "ATM"
    if _upper(option_type).startswith("CALL"):
        return "ITM" if underlying > strike else "OTM"
    if _upper(option_type).startswith("PUT"):
        return "ITM" if underlying < strike else "OTM"
    return "—"


def normalize_stocks(stocks: pd.DataFrame | None) -> pd.DataFrame:
    if stocks is None or stocks.empty:
        return pd.DataFrame(columns=STOCK_INPUT_COLUMNS)
    out = stocks.copy()
    for col in STOCK_INPUT_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[STOCK_INPUT_COLUMNS]
    out["Ativo"] = out["Ativo"].map(_upper)
    out["Quantidade"] = pd.to_numeric(out["Quantidade"], errors="coerce")
    out["Preço médio"] = pd.to_numeric(out["Preço médio"], errors="coerce")
    out["Cotação manual"] = pd.to_numeric(out["Cotação manual"], errors="coerce")
    return out[(out["Ativo"] != "") & (out["Quantidade"].fillna(0) != 0)].reset_index(drop=True)


def normalize_options(options: pd.DataFrame | None) -> pd.DataFrame:
    if options is None or options.empty:
        return pd.DataFrame(columns=OPTION_INPUT_COLUMNS)
    out = options.copy()
    for col in OPTION_INPUT_COLUMNS:
        if col not in out.columns:
            out[col] = None
    out = out[OPTION_INPUT_COLUMNS]
    out["Opção"] = out["Opção"].map(_upper)
    out["Ativo base"] = out["Ativo base"].map(_upper)
    out["Tipo"] = out["Tipo"].map(_upper)
    out["Operação"] = out["Operação"].map(_upper)
    out["Status"] = out["Status"].map(_upper)
    for col in ["Quantidade", "Preço médio", "Strike", "Preço encerramento", "Preço atual manual", "Delta manual"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["Vencimento"] = out["Vencimento"].map(lambda x: _text(x))
    return out[(out["Opção"] != "") & (out["Quantidade"].fillna(0) != 0)].reset_index(drop=True)


def build_stocks_view(stocks: pd.DataFrame | None, quotes: dict[str, float] | None = None) -> pd.DataFrame:
    stocks = normalize_stocks(stocks)
    quotes = quotes or {}
    rows: list[dict] = []
    for _, row in stocks.iterrows():
        ticker = _upper(row["Ativo"])
        qty = _num(row["Quantidade"], 0.0)
        avg = _num(row["Preço médio"])
        manual = _num(row["Cotação manual"])
        market = manual if math.isfinite(manual) else _num(quotes.get(ticker))
        cost = qty * avg if math.isfinite(avg) else float("nan")
        market_value = qty * market if math.isfinite(market) else float("nan")
        pnl = market_value - cost if math.isfinite(market_value) and math.isfinite(cost) else float("nan")
        pnl_pct = pnl / cost * 100 if math.isfinite(pnl) and cost else float("nan")
        rows.append({
            "Ativo": ticker,
            "Quantidade": qty,
            "Preço médio": avg,
            "Cotação": market,
            "Custo": cost,
            "Valor de mercado": market_value,
            "P/L ações": pnl,
            "P/L ações %": pnl_pct,
        })
    return pd.DataFrame(rows)


def build_options_view(
    options: pd.DataFrame | None,
    analytics: dict[str, dict] | None = None,
    stock_quotes: dict[str, float] | None = None,
    today: date | None = None,
) -> pd.DataFrame:
    options = normalize_options(options)
    analytics = analytics or {}
    stock_quotes = stock_quotes or {}
    today = today or date.today()
    rows: list[dict] = []

    for _, row in options.iterrows():
        symbol = _upper(row["Opção"])
        meta = analytics.get(symbol, {}) or {}
        underlying = _upper(meta.get("underlyingSymbol") or row["Ativo base"])
        option_type = _upper(meta.get("side") or row["Tipo"])
        if option_type == "CALL":
            option_type = "CALL"
        elif option_type == "PUT":
            option_type = "PUT"
        operation = _upper(row["Operação"]) or "VENDA"
        status = _upper(row["Status"]) or "ABERTA"
        qty = abs(_num(row["Quantidade"], 0.0))
        avg = _num(row["Preço médio"])
        strike_meta = _num(meta.get("strike"))
        strike_manual = _num(row["Strike"])
        strike = strike_meta if math.isfinite(strike_meta) else strike_manual
        manual_current = _num(row["Preço atual manual"])
        api_current = _num(meta.get("optionPrice"))
        current = manual_current if math.isfinite(manual_current) else api_current
        manual_delta = _num(row["Delta manual"])
        api_delta = _num(meta.get("delta"))
        delta = api_delta if math.isfinite(api_delta) else manual_delta
        sign = _option_sign(operation)
        is_open = _is_open(status)
        initial_cashflow = -sign * avg * qty if math.isfinite(avg) else float("nan")
        mtm = sign * (current - avg) * qty if is_open and math.isfinite(current) and math.isfinite(avg) else float("nan")
        close_px = _num(row["Preço encerramento"])
        realized = sign * (close_px - avg) * qty if not is_open and math.isfinite(close_px) and math.isfinite(avg) else float("nan")
        delta_equiv = sign * delta * qty if is_open and math.isfinite(delta) else 0.0
        underlying_px = _num(meta.get("underlyingPrice"))
        if not math.isfinite(underlying_px):
            underlying_px = _num(stock_quotes.get(underlying))
        expiry = _coerce_date(meta.get("expirationDate") or row["Vencimento"])
        dte = (expiry - today).days if expiry else float("nan")
        intrinsic = float("nan")
        if math.isfinite(underlying_px) and math.isfinite(strike):
            if option_type == "CALL":
                intrinsic = max(underlying_px - strike, 0.0)
            elif option_type == "PUT":
                intrinsic = max(strike - underlying_px, 0.0)
        extrinsic = current - intrinsic if math.isfinite(current) and math.isfinite(intrinsic) else float("nan")
        rows.append({
            "Opção": symbol,
            "Ativo base": underlying,
            "Tipo": option_type,
            "Operação": operation,
            "Status": status,
            "Quantidade": qty,
            "Preço médio": avg,
            "Preço atual": current,
            "Strike": strike,
            "Vencimento": expiry.isoformat() if expiry else _text(row["Vencimento"]),
            "DTE": dte,
            "Preço ativo": underlying_px,
            "Moneyness": _moneyness(option_type, underlying_px, strike),
            "Delta": delta,
            "Delta equivalente": delta_equiv,
            "Gamma": _num(meta.get("gamma")),
            "Theta": _num(meta.get("theta")),
            "Vega": _num(meta.get("vega")),
            "IV %": _num(meta.get("impliedVolatility")) * 100 if math.isfinite(_num(meta.get("impliedVolatility"))) else float("nan"),
            "Open interest": _num(meta.get("openInterest")),
            "Fonte preço": _text(meta.get("priceSource")) or ("manual" if math.isfinite(manual_current) else "—"),
            "Confiança": _text(meta.get("confidence")) or "—",
            "Data gregas": _text(meta.get("date")),
            "Prêmio inicial": initial_cashflow,
            "P/L MTM": mtm,
            "P/L realizado": realized,
            "Valor intrínseco": intrinsic,
            "Valor extrínseco": extrinsic,
            "Notional exercício": strike * qty if math.isfinite(strike) else float("nan"),
        })
    return pd.DataFrame(rows)


def build_asset_summary(stocks_view: pd.DataFrame, options_view: pd.DataFrame) -> pd.DataFrame:
    tickers = set()
    if stocks_view is not None and not stocks_view.empty:
        tickers.update(stocks_view["Ativo"].dropna().astype(str))
    if options_view is not None and not options_view.empty:
        tickers.update(options_view["Ativo base"].dropna().astype(str))

    rows: list[dict] = []
    for ticker in sorted(tickers):
        s = stocks_view[stocks_view["Ativo"] == ticker] if not stocks_view.empty else pd.DataFrame()
        o = options_view[options_view["Ativo base"] == ticker] if not options_view.empty else pd.DataFrame()
        stock_qty = float(s["Quantidade"].sum()) if not s.empty else 0.0
        stock_cost = float(s["Custo"].sum()) if not s.empty else 0.0
        stock_market = float(s["Valor de mercado"].sum()) if not s.empty else 0.0
        avg = stock_cost / stock_qty if stock_qty else float("nan")
        quote = _num(s["Cotação"].dropna().iloc[-1]) if not s.empty and s["Cotação"].notna().any() else float("nan")
        open_opts = o[o["Status"].map(_is_open)] if not o.empty else pd.DataFrame()
        sold_calls = open_opts[(open_opts["Operação"].str.startswith("VEND", na=False)) & (open_opts["Tipo"] == "CALL")] if not open_opts.empty else pd.DataFrame()
        sold_puts = open_opts[(open_opts["Operação"].str.startswith("VEND", na=False)) & (open_opts["Tipo"] == "PUT")] if not open_opts.empty else pd.DataFrame()
        call_qty = float(sold_calls["Quantidade"].sum()) if not sold_calls.empty else 0.0
        put_notional = float(sold_puts["Notional exercício"].sum()) if not sold_puts.empty else 0.0
        option_delta = float(open_opts["Delta equivalente"].sum()) if not open_opts.empty else 0.0
        option_mtm = float(open_opts["P/L MTM"].sum(skipna=True)) if not open_opts.empty else 0.0
        realized = float(o["P/L realizado"].sum(skipna=True)) if not o.empty else 0.0
        premiums = float(o["Prêmio inicial"].sum(skipna=True)) if not o.empty else 0.0
        stock_pnl = stock_market - stock_cost
        rows.append({
            "Ativo": ticker,
            "Qtd ações": stock_qty,
            "PM ações": avg,
            "Cotação": quote,
            "P/L ações": stock_pnl,
            "Calls vendidas": call_qty,
            "Cobertura calls %": min(call_qty / stock_qty * 100, 9999.0) if stock_qty else (float("inf") if call_qty else 0.0),
            "Notional puts vendidas": put_notional,
            "Prêmio inicial líquido": premiums,
            "P/L opções MTM": option_mtm,
            "P/L opções realizado": realized,
            "Delta opções (ações eq.)": option_delta,
            "Delta líquido (ações eq.)": stock_qty + option_delta,
            "P/L total atual": stock_pnl + option_mtm + realized,
        })
    return pd.DataFrame(rows)


def build_sheet_view(stocks_view: pd.DataFrame, options_view: pd.DataFrame) -> pd.DataFrame:
    """Generate a compact view inspired by the user's spreadsheet, one row per option/asset leg."""
    rows: list[dict] = []
    stock_map = {}
    if stocks_view is not None and not stocks_view.empty:
        for _, row in stocks_view.iterrows():
            stock_map[_upper(row["Ativo"])] = row

    if options_view is not None and not options_view.empty:
        for _, opt in options_view.iterrows():
            ticker = _upper(opt["Ativo base"])
            stock = stock_map.get(ticker)
            avg_stock = _num(stock.get("Preço médio")) if stock is not None else float("nan")
            strike = _num(opt["Strike"])
            qty = _num(opt["Quantidade"], 0.0)
            diff = strike - avg_stock if math.isfinite(strike) and math.isfinite(avg_stock) else float("nan")
            exercise_balance = float("nan")
            if opt["Tipo"] == "CALL" and _upper(opt["Operação"]).startswith("VEND") and math.isfinite(diff):
                exercise_balance = diff * qty
            total = 0.0
            any_total = False
            for value in [exercise_balance, _num(opt["Prêmio inicial"]), _num(opt["P/L realizado"])]:
                if math.isfinite(value):
                    total += value
                    any_total = True
            rows.append({
                "Ativo": ticker,
                "Preço médio": avg_stock,
                "Opção": opt["Opção"],
                "Tipo/posição": f"{opt['Tipo']} {_text(opt['Operação']).lower()}",
                "Strike": strike,
                "Diferença": diff,
                "Quantidade": qty,
                "Saldo no exercício": exercise_balance,
                "Prêmio inicial": _num(opt["Prêmio inicial"]),
                "P/L MTM": _num(opt["P/L MTM"]),
                "P/L realizado": _num(opt["P/L realizado"]),
                "Delta": _num(opt["Delta"]),
                "DTE": _num(opt["DTE"]),
                "TOTAL potencial/histórico": total if any_total else float("nan"),
            })

    option_underlyings = set(options_view["Ativo base"].astype(str)) if options_view is not None and not options_view.empty else set()
    for ticker, stock in stock_map.items():
        if ticker in option_underlyings:
            continue
        rows.append({
            "Ativo": ticker,
            "Preço médio": _num(stock["Preço médio"]),
            "Opção": "—",
            "Tipo/posição": "Ações",
            "Strike": float("nan"),
            "Diferença": float("nan"),
            "Quantidade": _num(stock["Quantidade"], 0.0),
            "Saldo no exercício": float("nan"),
            "Prêmio inicial": float("nan"),
            "P/L MTM": float("nan"),
            "P/L realizado": float("nan"),
            "Delta": 1.0,
            "DTE": float("nan"),
            "TOTAL potencial/histórico": _num(stock["P/L ações"]),
        })
    return pd.DataFrame(rows)


def portfolio_totals(stocks_view: pd.DataFrame, options_view: pd.DataFrame) -> dict:
    stock_cost = float(stocks_view["Custo"].sum(skipna=True)) if stocks_view is not None and not stocks_view.empty else 0.0
    stock_market = float(stocks_view["Valor de mercado"].sum(skipna=True)) if stocks_view is not None and not stocks_view.empty else 0.0
    stock_pnl = float(stocks_view["P/L ações"].sum(skipna=True)) if stocks_view is not None and not stocks_view.empty else 0.0
    option_mtm = 0.0
    realized = 0.0
    premium_cashflow = 0.0
    option_delta = 0.0
    short_put_notional = 0.0
    short_call_qty = 0.0
    if options_view is not None and not options_view.empty:
        open_mask = options_view["Status"].map(_is_open)
        open_opts = options_view[open_mask]
        option_mtm = float(open_opts["P/L MTM"].sum(skipna=True))
        realized = float(options_view["P/L realizado"].sum(skipna=True))
        premium_cashflow = float(options_view["Prêmio inicial"].sum(skipna=True))
        option_delta = float(open_opts["Delta equivalente"].sum(skipna=True))
        sold_puts = open_opts[(open_opts["Operação"].str.startswith("VEND", na=False)) & (open_opts["Tipo"] == "PUT")]
        sold_calls = open_opts[(open_opts["Operação"].str.startswith("VEND", na=False)) & (open_opts["Tipo"] == "CALL")]
        short_put_notional = float(sold_puts["Notional exercício"].sum(skipna=True))
        short_call_qty = float(sold_calls["Quantidade"].sum(skipna=True))
    stock_delta = float(stocks_view["Quantidade"].sum(skipna=True)) if stocks_view is not None and not stocks_view.empty else 0.0
    return {
        "stock_cost": stock_cost,
        "stock_market": stock_market,
        "stock_pnl": stock_pnl,
        "option_mtm": option_mtm,
        "option_realized": realized,
        "premium_cashflow": premium_cashflow,
        "net_pnl": stock_pnl + option_mtm + realized,
        "net_delta_equiv": stock_delta + option_delta,
        "short_put_notional": short_put_notional,
        "short_call_qty": short_call_qty,
    }
