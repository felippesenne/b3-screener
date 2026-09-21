import pandas as pd
import streamlit as st

from yahoo_audit import normalize_tickers, run_yahoo_audit


st.set_page_config(page_title="Auditoria Yahoo Finance", page_icon="🔎", layout="wide")

st.title("Auditoria técnica do Yahoo Finance")
st.caption(
    "Compara, sem cache do Streamlit, quatro rotas para cada ativo: yfinance individual, "
    "yfinance em lote, endpoint direto query1 e endpoint direto query2."
)

c1, c2 = st.columns([3, 1])
with c1:
    ticker_text = st.text_input(
        "Ativos para auditar",
        value="PETR4, VALE3, ITUB4",
        help="Separe por vírgula, ponto e vírgula ou quebra de linha.",
    )
with c2:
    period = st.selectbox("Período consultado", ["1mo", "3mo", "6mo", "1y", "2y"], index=0)

tickers = normalize_tickers(ticker_text)

run = st.button(
    "Executar auditoria agora",
    type="primary",
    use_container_width=True,
    disabled=not tickers,
)

if run:
    with st.spinner("Consultando Yahoo Finance pelas quatro rotas..."):
        try:
            st.session_state["yahoo_audit_result"] = run_yahoo_audit(tickers, period=period)
        except Exception as exc:
            st.error(f"A auditoria falhou: {exc}")
            st.stop()

result = st.session_state.get("yahoo_audit_result")
if not result:
    st.info("Clique em **Executar auditoria agora** para fazer uma consulta nova ao Yahoo Finance.")
    st.stop()

checked_at = result["checked_at"]
expected = result["expected_date"]
summary = result["summary"].copy()

m1, m2, m3 = st.columns(3)
m1.metric("Pregão esperado", expected.strftime("%d/%m/%Y"))
m2.metric("Consulta realizada", checked_at.strftime("%d/%m/%Y %H:%M:%S BRT"))
m3.metric("Ativos testados", len(summary))

st.subheader("Comparação das rotas")
for col in ["Pregão esperado", "yfinance individual", "yfinance lote", "query1 direto", "query2 direto"]:
    if col in summary.columns:
        summary[col] = summary[col].map(lambda x: x.strftime("%d/%m/%Y") if pd.notna(x) and x else "—")

st.dataframe(summary, use_container_width=True, hide_index=True)

st.caption(
    "Se `query2 direto` estiver atualizado e `yfinance individual` ou `yfinance lote` estiverem atrás, "
    "a discrepância está na camada do yfinance/download. Se todas as rotas estiverem atrás, "
    "o servidor que executa o app está recebendo dados defasados do Yahoo."
)

st.subheader("Detalhes por ativo")
for ticker, detail in result["details"].items():
    with st.expander(f"{ticker} — {detail['diagnosis']}", expanded=False):
        individual = detail["individual"]
        batch = detail["batch"]
        endpoints = detail["endpoints"]

        st.markdown("**yfinance**")
        y1, y2 = st.columns(2)
        with y1:
            st.write("Consulta individual")
            st.write(f"Último candle: **{individual['latest_date'].strftime('%d/%m/%Y') if individual['latest_date'] else 'indisponível'}**")
            st.write(f"Candles retornados: **{individual['rows']}**")
            if individual.get("error"):
                st.error(individual["error"])
            if individual.get("tail") is not None:
                st.dataframe(individual["tail"], use_container_width=True)
        with y2:
            st.write("Download em lote")
            st.write(f"Último candle: **{batch['latest_date'].strftime('%d/%m/%Y') if batch['latest_date'] else 'indisponível'}**")
            st.write(f"Candles retornados: **{batch['rows']}**")
            if batch.get("error"):
                st.error(batch["error"])
            if batch.get("tail") is not None:
                st.dataframe(batch["tail"], use_container_width=True)

        st.markdown("**Endpoints diretos do Yahoo**")
        for endpoint in endpoints:
            host_name = "query1" if "query1" in endpoint.host else "query2"
            st.write(
                f"{host_name}: HTTP **{endpoint.http_status if endpoint.http_status is not None else '—'}** · "
                f"último candle **{endpoint.latest_date.strftime('%d/%m/%Y') if endpoint.latest_date else 'indisponível'}** · "
                f"{endpoint.rows} timestamps"
            )
            if endpoint.error:
                st.error(endpoint.error)
            st.code(endpoint.url, language=None)
            if endpoint.meta:
                meta = endpoint.meta
                st.caption(
                    "Meta Yahoo: "
                    f"exchange={meta.get('exchangeName', '—')} · "
                    f"timezone={meta.get('exchangeTimezoneName', '—')} · "
                    f"currency={meta.get('currency', '—')}"
                )

st.divider()
st.caption(
    "Esta página é apenas diagnóstica. Ela não altera a fonte do Screener: as análises continuam usando Yahoo Finance via yfinance."
)
