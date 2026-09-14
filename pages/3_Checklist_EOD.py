from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from bdr_universe import BDRS
from data_provider import YahooFinanceProvider
from eod_checklist import scan_eod_universe
from universes import FAVORITE_23, IBOVESPA, fetch_all_b3_tickers, universe_text


st.set_page_config(page_title="Checklist EOD", page_icon="✅", layout="wide")

MARKET_TZ = ZoneInfo("America/Sao_Paulo")


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_all_b3_tickers() -> list[str]:
    return fetch_all_b3_tickers()


st.title("Checklist EOD")
st.caption(
    "Ranking de oportunidades para swing trade. Cruza tendência, Setup 9.1, IFR2, "
    "volta às médias, Dave Landry clássico, região técnica, volume e risco/retorno."
)

with st.sidebar:
    st.header("Varredura")
    scan_mode = st.radio(
        "Checklist",
        ["Diário", "Semanal"],
        horizontal=True,
        help="Diário: usar após o fechamento. Semanal: usar preferencialmente após o pregão de sexta-feira.",
    )

    universe_name = st.selectbox(
        "Universo",
        ["Ativos do Ibovespa", "Meus 23 ativos", "Todos os ativos da B3", "BDRs"],
        index=0,
    )

    if universe_name == "Ativos do Ibovespa":
        selected = IBOVESPA
    elif universe_name == "Meus 23 ativos":
        selected = FAVORITE_23
    elif universe_name == "BDRs":
        selected = BDRS
    else:
        try:
            selected = cached_all_b3_tickers()
        except Exception as exc:
            st.error(f"Não foi possível carregar todos os ativos da B3: {exc}")
            selected = IBOVESPA

    universe_key = f"{scan_mode}:{universe_name}"
    if st.session_state.get("_eod_loaded_universe") != universe_key:
        st.session_state["eod_ticker_text"] = universe_text(selected)
        st.session_state["_eod_loaded_universe"] = universe_key

    st.caption(f"{len(selected)} ativos carregados.")
    ticker_text = st.text_area("Tickers", height=120, key="eod_ticker_text")

    default_period = 3 if scan_mode == "Semanal" else 2
    history_period = st.selectbox(
        "Histórico",
        ["1y", "2y", "5y", "10y"],
        index=default_period,
        help="Para o checklist semanal, 5 anos ou mais é recomendado por causa das médias longas.",
    )

    minimum_score = st.slider("Nota mínima exibida", 0.0, 9.0, 5.0, 0.5)
    only_aligned = st.checkbox("Exigir alinhamento com timeframe maior", value=False)

st.info(
    "**Leitura da nota (0–9):** Tendência 0–2 + Setup 0–2 + Região técnica 0–2 + "
    "Volume 0–1 + Risco/Retorno 0–2. "
    "**A** = nota ≥7, setup pronto e timeframe maior alinhado; **B** = nota ≥5; **C** = monitoramento."
)

if scan_mode == "Diário":
    st.caption("Fluxo: semanal = direção → diário = setup → gatilho = entrada.")
else:
    now = datetime.now(MARKET_TZ)
    if now.weekday() != 4:
        st.warning(
            "O checklist semanal foi desenhado para o fechamento de sexta-feira. "
            "Quando a semana ainda está aberta, o sistema usa apenas o último candle semanal concluído."
        )
    st.caption("Fluxo: mensal = contexto → semanal = oportunidade → diário = refinamento da entrada.")

run = st.button("Rodar Checklist EOD", type="primary", use_container_width=True)

if run:
    raw_tickers = [line.strip().upper().replace(".SA", "") for line in ticker_text.splitlines() if line.strip()]
    tickers = list(dict.fromkeys(raw_tickers))

    if not tickers:
        st.error("Informe pelo menos um ticker.")
        st.stop()

    provider = YahooFinanceProvider()
    with st.spinner(f"Analisando {len(tickers)} ativos..."):
        result, errors = scan_eod_universe(
            tickers,
            provider,
            scan_mode=scan_mode,
            period=history_period,
        )

    if result.empty:
        st.warning("Nenhum ativo pôde ser analisado.")
    else:
        filtered = result[result["Nota"] >= minimum_score].copy()
        if only_aligned:
            filtered = filtered[filtered["Alinhado"] == "Sim"].copy()

        priority_a = int((filtered["Prioridade"] == "A").sum()) if not filtered.empty else 0
        priority_b = int((filtered["Prioridade"] == "B").sum()) if not filtered.empty else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Analisados", len(result))
        c2.metric("Exibidos", len(filtered))
        c3.metric("Prioridade A", priority_a)
        c4.metric("Prioridade B", priority_b)

        st.subheader("Ranking")
        if filtered.empty:
            st.info("Nenhum ativo atingiu os filtros atuais.")
        else:
            display_cols = [
                "Ticker", "Prioridade", "Nota", "Confluências", "Setups", "Tendência",
                "Tendência maior", "Alinhado", "IFR2", "ADX14", "Volume x média20",
                "Gatilho", "Stop", "Alvo técnico", "R/R", "Data",
            ]
            st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

            with st.expander("Detalhes do ranking"):
                detail_cols = [
                    "Ticker", "Status", "Região técnica", "Dist. MME21 (ATR)",
                    "Trend pts", "Setup pts", "Região pts", "Volume pts", "R/R pts",
                    "Regime ADX",
                ]
                st.dataframe(filtered[detail_cols], use_container_width=True, hide_index=True)

            st.download_button(
                "Baixar ranking em CSV",
                data=filtered.to_csv(index=False).encode("utf-8"),
                file_name=f"checklist_eod_{scan_mode.lower()}.csv",
                mime="text/csv",
            )

        with st.expander("Auditoria — todos os ativos"):
            st.dataframe(result, use_container_width=True, hide_index=True)

    if errors:
        with st.expander(f"Falhas de dados ({len(errors)})"):
            for ticker, message in errors.items():
                st.write(f"**{ticker}:** {message}")

st.divider()
st.caption(
    "Dados: Yahoo Finance via yfinance. O ranking é um filtro técnico de estudo, não uma recomendação de compra ou venda."
)
