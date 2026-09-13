from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st

from portfolio.calculations import (
    OPTION_INPUT_COLUMNS,
    STOCK_INPUT_COLUMNS,
    build_asset_summary,
    build_options_view,
    build_sheet_view,
    build_stocks_view,
    normalize_options,
    normalize_stocks,
    portfolio_totals,
)
from portfolio.market_data import fetch_option_analytics, fetch_stock_quotes


st.set_page_config(page_title="Carteira — Ações e Opções", page_icon="💼", layout="wide")


def fmt_brl(value) -> str:
    try:
        value = float(value)
    except Exception:
        return "—"
    if pd.isna(value):
        return "—"
    return (f"R$ {value:,.2f}").replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_num(value, digits: int = 2) -> str:
    try:
        value = float(value)
    except Exception:
        return "—"
    if pd.isna(value):
        return "—"
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def empty_stocks() -> pd.DataFrame:
    return pd.DataFrame([{"Ativo": "", "Quantidade": None, "Preço médio": None, "Cotação manual": None}], columns=STOCK_INPUT_COLUMNS)


def empty_options() -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "Opção": "",
            "Ativo base": "",
            "Tipo": "CALL",
            "Operação": "VENDA",
            "Quantidade": None,
            "Preço médio": None,
            "Strike": None,
            "Vencimento": "",
            "Status": "ABERTA",
            "Preço encerramento": None,
            "Preço atual manual": None,
            "Delta manual": None,
        }],
        columns=OPTION_INPUT_COLUMNS,
    )


def secret_token() -> str:
    try:
        return str(st.secrets.get("BRAPI_TOKEN", "") or "")
    except Exception:
        return ""


def json_records(df: pd.DataFrame) -> list[dict]:
    clean = df.copy().astype(object).where(pd.notna(df), None)
    return clean.to_dict(orient="records")


if "portfolio_stocks" not in st.session_state:
    st.session_state.portfolio_stocks = empty_stocks()
if "portfolio_options" not in st.session_state:
    st.session_state.portfolio_options = empty_options()
if "portfolio_quotes" not in st.session_state:
    st.session_state.portfolio_quotes = {}
if "portfolio_option_analytics" not in st.session_state:
    st.session_state.portfolio_option_analytics = {}
if "portfolio_market_errors" not in st.session_state:
    st.session_state.portfolio_market_errors = {}
if "portfolio_market_updated" not in st.session_state:
    st.session_state.portfolio_market_updated = None


st.title("Carteira — Ações e Opções")
st.caption(
    "Controle de posição, preço médio, prêmios, resultado a mercado e exposição por delta. "
    "As gregas são carregadas da brapi e representam o último fechamento disponível, não cotação intraday."
)

with st.expander("1. Posições da carteira", expanded=True):
    tab_stocks, tab_options = st.tabs(["Ações", "Opções"])
    with tab_stocks:
        st.caption("Cadastre as ações em carteira. Cotação manual é opcional e, quando preenchida, prevalece sobre a cotação automática.")
        stocks_edited = st.data_editor(
            st.session_state.portfolio_stocks,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="portfolio_stocks_editor",
            column_config={
                "Ativo": st.column_config.TextColumn("Ativo", help="Ex.: BBAS3"),
                "Quantidade": st.column_config.NumberColumn("Quantidade", step=100, format="%d"),
                "Preço médio": st.column_config.NumberColumn("Preço médio", step=0.01, format="R$ %.2f"),
                "Cotação manual": st.column_config.NumberColumn("Cotação manual", step=0.01, format="R$ %.2f", help="Opcional. Use se quiser sobrescrever o Yahoo Finance."),
            },
        )
        st.session_state.portfolio_stocks = stocks_edited

    with tab_options:
        st.caption(
            "Para delta/gregas automáticos informe Opção, Ativo base e Vencimento no formato YYYY-MM-DD. "
            "Preço atual e Delta manuais funcionam como fallback."
        )
        options_edited = st.data_editor(
            st.session_state.portfolio_options,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="portfolio_options_editor",
            column_config={
                "Opção": st.column_config.TextColumn("Opção", help="Ex.: PETRA..."),
                "Ativo base": st.column_config.TextColumn("Ativo base", help="Ex.: PETR4"),
                "Tipo": st.column_config.SelectboxColumn("Tipo", options=["CALL", "PUT"], required=False),
                "Operação": st.column_config.SelectboxColumn("Operação", options=["VENDA", "COMPRA"], required=True),
                "Quantidade": st.column_config.NumberColumn("Quantidade", min_value=0, step=100, format="%d"),
                "Preço médio": st.column_config.NumberColumn("Prêmio médio", min_value=0.0, step=0.01, format="R$ %.2f"),
                "Strike": st.column_config.NumberColumn("Strike", min_value=0.0, step=0.01, format="R$ %.2f"),
                "Vencimento": st.column_config.TextColumn("Vencimento", help="YYYY-MM-DD"),
                "Status": st.column_config.SelectboxColumn("Status", options=["ABERTA", "ENCERRADA"], required=True),
                "Preço encerramento": st.column_config.NumberColumn("Preço encerramento", min_value=0.0, step=0.01, format="R$ %.2f"),
                "Preço atual manual": st.column_config.NumberColumn("Preço atual manual", min_value=0.0, step=0.01, format="R$ %.2f"),
                "Delta manual": st.column_config.NumberColumn("Delta manual", min_value=-1.0, max_value=1.0, step=0.01, format="%.3f"),
            },
        )
        st.session_state.portfolio_options = options_edited


with st.expander("2. Mercado, delta e backup", expanded=True):
    c1, c2 = st.columns([2, 1])
    with c1:
        token = st.text_input(
            "Token brapi (opcional para PETR4; necessário para as demais opções)",
            value=secret_token(),
            type="password",
            help="O token não entra no arquivo de backup da carteira. Em produção, prefira configurar BRAPI_TOKEN nos Secrets do Streamlit.",
        )
    with c2:
        refresh = st.button("Atualizar mercado e gregas", type="primary", use_container_width=True)

    if refresh:
        stocks_clean = normalize_stocks(st.session_state.portfolio_stocks)
        options_clean = normalize_options(st.session_state.portfolio_options)
        stock_tickers = list(stocks_clean["Ativo"].dropna().astype(str))
        option_underlyings = list(options_clean["Ativo base"].dropna().astype(str))
        tickers = sorted(set(stock_tickers + option_underlyings))
        with st.spinner("Atualizando ações e opções..."):
            quotes, quote_errors = fetch_stock_quotes(tickers)
            analytics, option_errors, _ = fetch_option_analytics(options_clean, token=token)
        st.session_state.portfolio_quotes = quotes
        st.session_state.portfolio_option_analytics = analytics
        st.session_state.portfolio_market_errors = {**{f"Cotação {k}": v for k, v in quote_errors.items()}, **option_errors}
        st.session_state.portfolio_market_updated = pd.Timestamp.now().strftime("%d/%m/%Y %H:%M:%S")
        st.success("Mercado atualizado.")

    if st.session_state.portfolio_market_updated:
        st.caption(f"Última atualização solicitada: {st.session_state.portfolio_market_updated}")

    backup = {
        "version": 1,
        "stocks": json_records(pd.DataFrame(st.session_state.portfolio_stocks)),
        "options": json_records(pd.DataFrame(st.session_state.portfolio_options)),
    }
    b1, b2 = st.columns(2)
    with b1:
        st.download_button(
            "Baixar backup JSON",
            data=json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="carteira_b3.json",
            mime="application/json",
            use_container_width=True,
        )
    with b2:
        upload = st.file_uploader("Restaurar backup JSON", type=["json"], label_visibility="collapsed")
        if upload is not None and st.button("Importar backup", use_container_width=True):
            try:
                payload = json.loads(upload.getvalue().decode("utf-8"))
                st.session_state.portfolio_stocks = pd.DataFrame(payload.get("stocks") or [], columns=STOCK_INPUT_COLUMNS)
                st.session_state.portfolio_options = pd.DataFrame(payload.get("options") or [], columns=OPTION_INPUT_COLUMNS)
                if st.session_state.portfolio_stocks.empty:
                    st.session_state.portfolio_stocks = empty_stocks()
                if st.session_state.portfolio_options.empty:
                    st.session_state.portfolio_options = empty_options()
                st.session_state.pop("portfolio_stocks_editor", None)
                st.session_state.pop("portfolio_options_editor", None)
                st.success("Backup importado.")
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível importar o backup: {exc}")


stocks_view = build_stocks_view(st.session_state.portfolio_stocks, st.session_state.portfolio_quotes)
options_view = build_options_view(
    st.session_state.portfolio_options,
    analytics=st.session_state.portfolio_option_analytics,
    stock_quotes=st.session_state.portfolio_quotes,
    today=date.today(),
)
summary = build_asset_summary(stocks_view, options_view)
sheet_view = build_sheet_view(stocks_view, options_view)
totals = portfolio_totals(stocks_view, options_view)

st.divider()
st.subheader("Visão geral")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Ações a mercado", fmt_brl(totals["stock_market"]))
c2.metric("P/L ações", fmt_brl(totals["stock_pnl"]))
c3.metric("P/L opções MTM", fmt_brl(totals["option_mtm"]))
c4.metric("P/L opções realizado", fmt_brl(totals["option_realized"]))
c5.metric("P/L total atual", fmt_brl(totals["net_pnl"]))
c6.metric("Delta líquido (ações eq.)", fmt_num(totals["net_delta_equiv"], 0))

c7, c8, c9 = st.columns(3)
c7.metric("Prêmio inicial líquido", fmt_brl(totals["premium_cashflow"]))
c8.metric("Notional puts vendidas", fmt_brl(totals["short_put_notional"]))
c9.metric("Calls vendidas (qtd.)", fmt_num(totals["short_call_qty"], 0))

alerts: list[str] = []
if not summary.empty:
    uncovered = summary[(summary["Calls vendidas"] > summary["Qtd ações"]) & (summary["Calls vendidas"] > 0)]
    for _, row in uncovered.iterrows():
        alerts.append(f"{row['Ativo']}: há mais calls vendidas ({int(row['Calls vendidas'])}) do que ações ({int(row['Qtd ações'])}).")
if not options_view.empty:
    expiring = options_view[(options_view["Status"].map(lambda x: not str(x).upper().startswith("ENCERR"))) & (pd.to_numeric(options_view["DTE"], errors="coerce") <= 7) & (pd.to_numeric(options_view["DTE"], errors="coerce") >= 0)]
    for _, row in expiring.iterrows():
        alerts.append(f"{row['Opção']}: vence em {int(row['DTE'])} dia(s).")
if alerts:
    with st.expander(f"Alertas de posição ({len(alerts)})", expanded=True):
        for message in alerts:
            st.warning(message)

if st.session_state.portfolio_market_errors:
    with st.expander(f"Dados não atualizados / avisos ({len(st.session_state.portfolio_market_errors)})"):
        for key, message in st.session_state.portfolio_market_errors.items():
            st.write(f"**{key}:** {message}")


def money_cols() -> dict:
    return {
        "Preço médio": st.column_config.NumberColumn(format="R$ %.2f"),
        "Cotação": st.column_config.NumberColumn(format="R$ %.2f"),
        "Custo": st.column_config.NumberColumn(format="R$ %.2f"),
        "Valor de mercado": st.column_config.NumberColumn(format="R$ %.2f"),
        "P/L ações": st.column_config.NumberColumn(format="R$ %.2f"),
        "Preço atual": st.column_config.NumberColumn(format="R$ %.2f"),
        "Strike": st.column_config.NumberColumn(format="R$ %.2f"),
        "Preço ativo": st.column_config.NumberColumn(format="R$ %.2f"),
        "Prêmio inicial": st.column_config.NumberColumn(format="R$ %.2f"),
        "P/L MTM": st.column_config.NumberColumn(format="R$ %.2f"),
        "P/L realizado": st.column_config.NumberColumn(format="R$ %.2f"),
        "Notional exercício": st.column_config.NumberColumn(format="R$ %.2f"),
    }


st.subheader("Posição consolidada")
tab_summary, tab_sheet, tab_stocks_out, tab_options_out = st.tabs([
    "Por ativo",
    "Visão estilo planilha",
    "Ações",
    "Opções + gregas",
])

with tab_summary:
    if summary.empty:
        st.info("Cadastre ações ou opções para montar o consolidado.")
    else:
        st.dataframe(
            summary,
            use_container_width=True,
            hide_index=True,
            column_config={
                "PM ações": st.column_config.NumberColumn(format="R$ %.2f"),
                "Cotação": st.column_config.NumberColumn(format="R$ %.2f"),
                "P/L ações": st.column_config.NumberColumn(format="R$ %.2f"),
                "Cobertura calls %": st.column_config.NumberColumn(format="%.1f%%"),
                "Notional puts vendidas": st.column_config.NumberColumn(format="R$ %.2f"),
                "Prêmio inicial líquido": st.column_config.NumberColumn(format="R$ %.2f"),
                "P/L opções MTM": st.column_config.NumberColumn(format="R$ %.2f"),
                "P/L opções realizado": st.column_config.NumberColumn(format="R$ %.2f"),
                "Delta opções (ações eq.)": st.column_config.NumberColumn(format="%.1f"),
                "Delta líquido (ações eq.)": st.column_config.NumberColumn(format="%.1f"),
                "P/L total atual": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

with tab_sheet:
    if sheet_view.empty:
        st.info("Sem operações para exibir.")
    else:
        st.caption(
            "Visão inspirada na planilha enviada. Em calls vendidas cobertas, 'Saldo no exercício' = (strike − PM da ação) × quantidade."
        )
        st.dataframe(
            sheet_view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Preço médio": st.column_config.NumberColumn(format="R$ %.2f"),
                "Strike": st.column_config.NumberColumn(format="R$ %.2f"),
                "Diferença": st.column_config.NumberColumn(format="R$ %.2f"),
                "Saldo no exercício": st.column_config.NumberColumn(format="R$ %.2f"),
                "Prêmio inicial": st.column_config.NumberColumn(format="R$ %.2f"),
                "P/L MTM": st.column_config.NumberColumn(format="R$ %.2f"),
                "P/L realizado": st.column_config.NumberColumn(format="R$ %.2f"),
                "Delta": st.column_config.NumberColumn(format="%.3f"),
                "TOTAL potencial/histórico": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

with tab_stocks_out:
    if stocks_view.empty:
        st.info("Nenhuma ação cadastrada.")
    else:
        st.dataframe(stocks_view, use_container_width=True, hide_index=True, column_config=money_cols())

with tab_options_out:
    if options_view.empty:
        st.info("Nenhuma opção cadastrada.")
    else:
        st.dataframe(
            options_view,
            use_container_width=True,
            hide_index=True,
            column_config={
                **money_cols(),
                "Delta": st.column_config.NumberColumn(format="%.4f"),
                "Delta equivalente": st.column_config.NumberColumn(format="%.1f"),
                "Gamma": st.column_config.NumberColumn(format="%.5f"),
                "Theta": st.column_config.NumberColumn(format="%.4f"),
                "Vega": st.column_config.NumberColumn(format="%.4f"),
                "IV %": st.column_config.NumberColumn(format="%.2f%%"),
                "Open interest": st.column_config.NumberColumn(format="%.0f"),
                "Valor intrínseco": st.column_config.NumberColumn(format="R$ %.2f"),
                "Valor extrínseco": st.column_config.NumberColumn(format="R$ %.2f"),
            },
        )

st.divider()
st.caption(
    "Privacidade: a carteira não é gravada no repositório público. Nesta versão ela permanece na sessão do Streamlit; "
    "use o backup JSON para restaurá-la depois. O token brapi não é incluído no backup."
)
