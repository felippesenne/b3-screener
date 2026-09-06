import streamlit as st

from data_provider import YahooFinanceProvider
from scanner import describe_strategy, scan_universe

st.set_page_config(page_title="B3 Strategy Builder", page_icon="📈", layout="wide")

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

INDICATORS = [
    "Preço", "IFR (RSI)", "MME (EMA)", "MMS (SMA)", "MACD",
    "Bandas de Bollinger", "Estocástico", "ADX / DI", "ATR", "Volume",
]
OPERATORS = {
    "Maior que (>)": ">",
    "Maior ou igual (>=)": ">=",
    "Menor que (<)": "<",
    "Menor ou igual (<=)": "<=",
    "Igual (=)": "==",
    "Cruza acima": "crosses_above",
    "Cruza abaixo": "crosses_below",
    "Ascendente": "rising",
    "Descendente": "falling",
}


def indicator_editor(prefix: str, default_type="IFR (RSI)") -> dict:
    choice = st.selectbox("Indicador", INDICATORS, index=INDICATORS.index(default_type), key=f"{prefix}_kind")

    if choice == "Preço":
        field_label = st.selectbox("Preço", ["Fechamento", "Abertura", "Máxima", "Mínima"], key=f"{prefix}_field")
        field = {"Fechamento": "Close", "Abertura": "Open", "Máxima": "High", "Mínima": "Low"}[field_label]
        return {"kind": "PRICE", "field": field}

    if choice == "IFR (RSI)":
        period = st.number_input("Período IFR", 2, 200, 14, key=f"{prefix}_period")
        return {"kind": "RSI", "period": int(period)}

    if choice == "MME (EMA)":
        period = st.number_input("Período MME", 2, 500, 9, key=f"{prefix}_period")
        return {"kind": "EMA", "period": int(period)}

    if choice == "MMS (SMA)":
        period = st.number_input("Período MMS", 2, 500, 20, key=f"{prefix}_period")
        return {"kind": "SMA", "period": int(period)}

    if choice == "MACD":
        c1, c2, c3 = st.columns(3)
        fast = c1.number_input("Rápida", 2, 100, 12, key=f"{prefix}_fast")
        slow = c2.number_input("Lenta", 3, 200, 26, key=f"{prefix}_slow")
        signal = c3.number_input("Sinal", 2, 100, 9, key=f"{prefix}_signal")
        output_label = st.selectbox("Saída", ["Linha MACD", "Linha de sinal", "Histograma"], key=f"{prefix}_output")
        output = {"Linha MACD": "macd", "Linha de sinal": "signal", "Histograma": "hist"}[output_label]
        return {"kind": "MACD", "fast": int(fast), "slow": int(slow), "signal": int(signal), "output": output}

    if choice == "Bandas de Bollinger":
        c1, c2 = st.columns(2)
        period = c1.number_input("Período", 2, 300, 20, key=f"{prefix}_period")
        std = c2.number_input("Desvios", 0.1, 5.0, 2.0, 0.1, key=f"{prefix}_std")
        output_label = st.selectbox("Saída", ["Banda superior", "Média", "Banda inferior", "%B", "Bandwidth"], key=f"{prefix}_output")
        output = {"Banda superior": "upper", "Média": "middle", "Banda inferior": "lower", "%B": "pctb", "Bandwidth": "bandwidth"}[output_label]
        return {"kind": "BB", "period": int(period), "std": float(std), "output": output}

    if choice == "Estocástico":
        c1, c2, c3 = st.columns(3)
        k = c1.number_input("%K", 2, 100, 14, key=f"{prefix}_k")
        smooth = c2.number_input("Suavização K", 1, 20, 3, key=f"{prefix}_smooth")
        d = c3.number_input("%D", 1, 20, 3, key=f"{prefix}_d")
        output_label = st.selectbox("Saída", ["%K", "%D"], key=f"{prefix}_output")
        return {"kind": "STOCH", "k_period": int(k), "smooth_k": int(smooth), "d_period": int(d), "output": "k" if output_label == "%K" else "d"}

    if choice == "ADX / DI":
        period = st.number_input("Período ADX", 2, 100, 14, key=f"{prefix}_period")
        output_label = st.selectbox("Saída", ["ADX", "+DI", "-DI"], key=f"{prefix}_output")
        output = {"ADX": "adx", "+DI": "plus_di", "-DI": "minus_di"}[output_label]
        return {"kind": "ADX", "period": int(period), "output": output}

    if choice == "ATR":
        period = st.number_input("Período ATR", 2, 100, 14, key=f"{prefix}_period")
        return {"kind": "ATR", "period": int(period)}

    period = st.number_input("Período da média de volume", 2, 300, 20, key=f"{prefix}_period")
    output_label = st.selectbox("Saída", ["Volume atual", "Média de volume", "Volume / média"], key=f"{prefix}_output")
    output = {"Volume atual": "volume", "Média de volume": "average", "Volume / média": "ratio"}[output_label]
    return {"kind": "VOLUME", "period": int(period), "output": output}


def preset_rules(name: str):
    if name == "IFR2 < 25 + MME50 ascendente":
        return [
            {"left": {"kind": "RSI", "period": 2}, "operator": "<", "right_kind": "value", "right_value": 25.0},
            {"connector": "AND", "left": {"kind": "EMA", "period": 50}, "operator": "rising"},
        ]
    if name == "Setup MME9 / MME80":
        return [
            {"left": {"kind": "EMA", "period": 9}, "operator": "rising"},
            {"connector": "AND", "left": {"kind": "EMA", "period": 80}, "operator": "rising"},
        ]
    return None


st.title("B3 Strategy Builder")
st.caption("Monte scanners técnicos combinando indicadores, parâmetros, comparações e cruzamentos sem alterar código.")

with st.sidebar:
    st.header("Universo")
    ticker_text = st.text_area("Tickers da B3", value=DEFAULT_TICKERS, height=230)
    timeframe = st.selectbox("Timeframe", ["Diário", "Semanal", "Mensal"])
    history_period = st.selectbox("Histórico", ["6mo", "1y", "2y", "5y", "10y"], index=2)
    st.divider()
    preset = st.selectbox("Atalho / preset", ["Strategy Builder", "IFR2 < 25 + MME50 ascendente", "Setup MME9 / MME80"])

rules = preset_rules(preset)

if rules is None:
    st.subheader("Construtor de estratégia")
    st.caption("As regras são avaliadas da esquerda para a direita. Cada condição a partir da segunda pode usar AND ou OR.")
    rule_count = st.number_input("Número de condições", min_value=1, max_value=10, value=2, step=1)
    rules = []

    for i in range(int(rule_count)):
        with st.expander(f"Condição {i + 1}", expanded=True):
            if i > 0:
                connector = st.radio("Conector com a condição anterior", ["AND", "OR"], horizontal=True, key=f"rule_{i}_connector")
            else:
                connector = None

            st.markdown("**Lado esquerdo**")
            left = indicator_editor(f"rule_{i}_left", default_type="IFR (RSI)" if i == 0 else "MME (EMA)")
            operator_label = st.selectbox("Condição", list(OPERATORS.keys()), key=f"rule_{i}_operator")
            op = OPERATORS[operator_label]

            rule = {"left": left, "operator": op}
            if connector:
                rule["connector"] = connector

            if op not in {"rising", "falling"}:
                compare_with = st.selectbox("Comparar com", ["Valor fixo", "Preço de fechamento", "Outro indicador"], key=f"rule_{i}_right_kind")
                if compare_with == "Valor fixo":
                    value = st.number_input("Valor", value=0.0, step=0.1, format="%.4f", key=f"rule_{i}_value")
                    rule.update({"right_kind": "value", "right_value": float(value)})
                elif compare_with == "Preço de fechamento":
                    rule.update({"right_kind": "price"})
                else:
                    st.markdown("**Lado direito**")
                    right = indicator_editor(f"rule_{i}_right", default_type="MME (EMA)")
                    rule.update({"right_kind": "indicator", "right": right})

            rules.append(rule)
else:
    st.subheader("Preset carregado")
    st.info(describe_strategy(rules))

st.subheader("Estratégia atual")
st.code(describe_strategy(rules), language=None)

run = st.button("Rodar screener", type="primary", use_container_width=True)

if run:
    tickers = [line.strip().upper().replace(".SA", "") for line in ticker_text.splitlines() if line.strip()]
    if not tickers:
        st.error("Informe pelo menos um ticker.")
        st.stop()

    provider = YahooFinanceProvider()
    with st.spinner(f"Analisando {len(tickers)} ativos..."):
        result, errors = scan_universe(tickers, provider, timeframe, history_period, rules)

    if result.empty:
        st.warning("Nenhum ativo pôde ser analisado.")
    else:
        passed = result[result["Passou"] == True].copy()
        c1, c2, c3 = st.columns(3)
        c1.metric("Ativos analisados", len(result))
        c2.metric("Selecionados", len(passed))
        c3.metric("Taxa de seleção", f"{(len(passed) / len(result) * 100):.1f}%")

        st.subheader("Selecionados")
        if passed.empty:
            st.info("Nenhum ativo passou pela estratégia atual.")
        else:
            st.dataframe(passed, use_container_width=True, hide_index=True)

        with st.expander("Auditoria — todos os ativos e condições"):
            st.dataframe(result, use_container_width=True, hide_index=True)

        st.download_button(
            "Baixar selecionados em CSV",
            data=passed.to_csv(index=False).encode("utf-8"),
            file_name="b3_strategy_builder.csv",
            mime="text/csv",
        )

    if errors:
        with st.expander(f"Falhas de dados ({len(errors)})"):
            for ticker, msg in errors.items():
                st.write(f"**{ticker}:** {msg}")

st.divider()
st.caption("Dados do MVP: Yahoo Finance via yfinance. Para decisões profissionais, use uma fonte de mercado contratada/licenciada.")
