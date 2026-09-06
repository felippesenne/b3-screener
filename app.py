import streamlit as st
import pandas as pd

from data_provider import YahooFinanceProvider
from scanner import scan_universe

st.set_page_config(
    page_title="B3 Screener",
    page_icon="📈",
    layout="wide",
)

DEFAULT_TICKERS = """AXIA3
B3SA3
BBAS3
BBDC4
BBSE3
BPAC11
CMIG4
CPFE3
CPLE3
CSMG3
CXSE3
EGIE3
ISAE4
ITUB4
PETR4
PRIO3
PSSA3
SANB11
SBSP3
TAEE11
TIMS3
VALE3
VIVT3"""

st.title("B3 Screener")
st.caption("MVP em Streamlit — dados históricos, indicadores técnicos e filtros combináveis.")

with st.sidebar:
    st.header("Universo")
    ticker_text = st.text_area(
        "Tickers da B3",
        value=DEFAULT_TICKERS,
        height=250,
        help="Um ticker por linha. O app adiciona .SA automaticamente para consulta no Yahoo Finance."
    )

    timeframe = st.selectbox(
        "Timeframe",
        ["Diário", "Semanal", "Mensal"],
        index=0,
    )

    history_period = st.selectbox(
        "Histórico",
        ["6mo", "1y", "2y", "5y"],
        index=2,
    )

    st.divider()
    st.header("Preset")
    preset = st.selectbox(
        "Estratégia",
        [
            "Personalizado",
            "IFR2 < 25 + MME50 ascendente",
            "Setup MME9 / MME80",
        ],
    )

    st.divider()
    st.header("Filtros")

    use_rsi = st.checkbox("Usar IFR(2)", value=True)
    rsi_operator = st.selectbox("IFR(2)", ["<", "<=", ">", ">="], index=0)
    rsi_value = st.number_input("Valor IFR(2)", min_value=0.0, max_value=100.0, value=25.0, step=1.0)

    use_ema50_slope = st.checkbox("MME50 ascendente", value=True)
    use_ema9_slope = st.checkbox("MME9 ascendente", value=False)
    use_ema80_slope = st.checkbox("MME80 ascendente", value=False)
    use_price_above_ema200 = st.checkbox("Preço acima da MME200", value=False)

    run = st.button("Rodar screener", type="primary", use_container_width=True)

if preset == "IFR2 < 25 + MME50 ascendente":
    use_rsi = True
    rsi_operator = "<"
    rsi_value = 25.0
    use_ema50_slope = True
    use_ema9_slope = False
    use_ema80_slope = False
    use_price_above_ema200 = False

elif preset == "Setup MME9 / MME80":
    use_rsi = False
    use_ema50_slope = False
    use_ema9_slope = True
    use_ema80_slope = True
    use_price_above_ema200 = False

if run:
    tickers = [
        line.strip().upper().replace(".SA", "")
        for line in ticker_text.splitlines()
        if line.strip()
    ]

    if not tickers:
        st.error("Informe pelo menos um ticker.")
        st.stop()

    rules = {
        "use_rsi": use_rsi,
        "rsi_operator": rsi_operator,
        "rsi_value": float(rsi_value),
        "ema50_up": use_ema50_slope,
        "ema9_up": use_ema9_slope,
        "ema80_up": use_ema80_slope,
        "price_above_ema200": use_price_above_ema200,
    }

    provider = YahooFinanceProvider()

    with st.spinner(f"Analisando {len(tickers)} ativos..."):
        result, errors = scan_universe(
            tickers=tickers,
            provider=provider,
            timeframe=timeframe,
            period=history_period,
            rules=rules,
        )

    if result.empty:
        st.warning("Nenhum ativo passou pelos filtros selecionados.")
    else:
        passed = result[result["Passou"] == True].copy()
        all_assets = result.copy()

        c1, c2, c3 = st.columns(3)
        c1.metric("Ativos analisados", len(result))
        c2.metric("Selecionados", len(passed))
        c3.metric("Taxa de seleção", f"{(len(passed)/len(result))*100:.1f}%")

        st.subheader("Selecionados")
        if passed.empty:
            st.info("Nenhum ativo passou por todos os critérios.")
        else:
            display_cols = [
                "Ticker", "Fechamento", "IFR2",
                "MME9", "MME50", "MME80", "MME200",
                "MME9 ↑", "MME50 ↑", "MME80 ↑",
                "Acima MME200", "Data"
            ]
            st.dataframe(
                passed[display_cols],
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Ver todos os ativos"):
            st.dataframe(all_assets, use_container_width=True, hide_index=True)

        csv = passed.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Baixar selecionados em CSV",
            data=csv,
            file_name="b3_screener_resultados.csv",
            mime="text/csv",
        )

    if errors:
        with st.expander(f"Falhas de dados ({len(errors)})"):
            for ticker, msg in errors.items():
                st.write(f"**{ticker}:** {msg}")

st.divider()
st.caption(
    "Fonte de dados do MVP: Yahoo Finance via yfinance. "
    "Para uso profissional, recomenda-se substituir por uma fonte contratada/licenciada e com SLA."
)
