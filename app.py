import streamlit as st

from data_provider import YahooFinanceProvider
from scanner import describe_strategy, scan_universe

st.set_page_config(page_title="B3 Strategy Builder", page_icon="📈", layout="wide")

DEFAULT_TICKERS = """ABEV3
ALOS3
ASAI3
AURE3
AXIA3
AXIA6
AZZA3
B3SA3
BBAS3
BBDC3
BBDC4
BBSE3
BEEF3
BPAC11
BRAP4
BRAV3
BRKM5
CEAB3
CMIG4
CMIN3
COGN3
CPFE3
CPLE3
CSAN3
CSMG3
CSNA3
CURY3
CXSE3
CYRE3
DIRR3
EGIE3
EMBJ3
ENEV3
ENGI11
EQTL3
FLRY3
GGBR4
GOAU4
HAPV3
HYPE3
IGTI11
ISAE4
ITSA4
ITUB4
KLBN11
LREN3
MBRF3
MGLU3
MOTV3
MRVE3
MULT3
NATU3
PETR3
PETR4
POMO4
PRIO3
PSSA3
RADL3
RAIL3
RDOR3
RECV3
RENT3
SANB11
SBSP3
SLCE3
SMFT3
SUZB3
TAEE11
TIMS3
TOTS3
UGPA3
USIM5
VALE3
VAMO3
VBBR3
VIVA3
VIVT3
WEGE3
YDUQ3"""

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

# Streamlit exige que toda chave de widget seja única dentro de uma execução.
# O contador por prefixo protege o Strategy Builder mesmo se um editor for
# renderizado mais de uma vez no mesmo ciclo por mudanças dinâmicas da interface.
_EDITOR_OCCURRENCES = {}


def _editor_scope(prefix: str) -> str:
    occurrence = _EDITOR_OCCURRENCES.get(prefix, 0)
    _EDITOR_OCCURRENCES[prefix] = occurrence + 1
    return f"{prefix}__{occurrence}"


def indicator_editor(prefix: str, default_type="IFR (RSI)") -> dict:
    scope = _editor_scope(prefix)
    choice = st.selectbox(
        "Indicador",
        INDICATORS,
        index=INDICATORS.index(default_type),
        key=f"{scope}_kind",
    )

    if choice == "Preço":
        field_label = st.selectbox(
            "Preço",
            ["Fechamento", "Abertura", "Máxima", "Mínima"],
            key=f"{scope}_field",
        )
        field = {"Fechamento": "Close", "Abertura": "Open", "Máxima": "High", "Mínima": "Low"}[field_label]
        return {"kind": "PRICE", "field": field}

    if choice == "IFR (RSI)":
        period = st.number_input("Período IFR", 2, 200, 14, key=f"{scope}_rsi_period")
        return {"kind": "RSI", "period": int(period)}

    if choice == "MME (EMA)":
        period = st.number_input("Período MME", 2, 500, 9, key=f"{scope}_ema_period")
        return {"kind": "EMA", "period": int(period)}

    if choice == "MMS (SMA)":
        period = st.number_input("Período MMS", 2, 500, 20, key=f"{scope}_sma_period")
        return {"kind": "SMA", "period": int(period)}

    if choice == "MACD":
        c1, c2, c3 = st.columns(3)
        fast = c1.number_input("Rápida", 2, 100, 12, key=f"{scope}_macd_fast")
        slow = c2.number_input("Lenta", 3, 200, 26, key=f"{scope}_macd_slow")
        signal = c3.number_input("Sinal", 2, 100, 9, key=f"{scope}_macd_signal")
        output_label = st.selectbox(
            "Saída",
            ["Linha MACD", "Linha de sinal", "Histograma"],
            key=f"{scope}_macd_output",
        )
        output = {"Linha MACD": "macd", "Linha de sinal": "signal", "Histograma": "hist"}[output_label]
        return {"kind": "MACD", "fast": int(fast), "slow": int(slow), "signal": int(signal), "output": output}

    if choice == "Bandas de Bollinger":
        c1, c2 = st.columns(2)
        period = c1.number_input("Período", 2, 300, 20, key=f"{scope}_bb_period")
        std = c2.number_input("Desvios", 0.1, 5.0, 2.0, 0.1, key=f"{scope}_bb_std")
        output_label = st.selectbox(
            "Saída",
            ["Banda superior", "Média", "Banda inferior", "%B", "Bandwidth"],
            key=f"{scope}_bb_output",
        )
        output = {"Banda superior": "upper", "Média": "middle", "Banda inferior": "lower", "%B": "pctb", "Bandwidth": "bandwidth"}[output_label]
        return {"kind": "BB", "period": int(period), "std": float(std), "output": output}

    if choice == "Estocástico":
        c1, c2, c3 = st.columns(3)
        k = c1.number_input("%K", 2, 100, 14, key=f"{scope}_stoch_k")
        smooth = c2.number_input("Suavização K", 1, 20, 3, key=f"{scope}_stoch_smooth")
        d = c3.number_input("%D", 1, 20, 3, key=f"{scope}_stoch_d")
        output_label = st.selectbox("Saída", ["%K", "%D"], key=f"{scope}_stoch_output")
        return {"kind": "STOCH", "k_period": int(k), "smooth_k": int(smooth), "d_period": int(d), "output": "k" if output_label == "%K" else "d"}

    if choice == "ADX / DI":
        period = st.number_input("Período ADX", 2, 100, 14, key=f"{scope}_adx_period")
        output_label = st.selectbox("Saída", ["ADX", "+DI", "-DI"], key=f"{scope}_adx_output")
        output = {"ADX": "adx", "+DI": "plus_di", "-DI": "minus_di"}[output_label]
        return {"kind": "ADX", "period": int(period), "output": output}

    if choice == "ATR":
        period = st.number_input("Período ATR", 2, 100, 14, key=f"{scope}_atr_period")
        return {"kind": "ATR", "period": int(period)}

    period = st.number_input("Período da média de volume", 2, 300, 20, key=f"{scope}_volume_period")
    output_label = st.selectbox(
        "Saída",
        ["Volume atual", "Média de volume", "Volume / média"],
        key=f"{scope}_volume_output",
    )
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
    ticker_text = st.text_area(
        "Ativos do Ibovespa",
        value=DEFAULT_TICKERS,
        height=420,
        help="Carteira oficial vigente do Ibovespa B3. A lista continua editável.",
    )
    st.caption("79 ativos na carteira padrão do Ibovespa.")
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
st.caption("Dados: Yahoo Finance via yfinance. O screener consulta o histórico disponível a cada execução.")
