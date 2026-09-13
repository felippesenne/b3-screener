from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from bdr_universe import BDRS
from classic_setups import CONTEXT_FILTERS, describe_context_filters
from data_provider import YahooFinanceProvider
from scanner import describe_strategy, scan_universe
from strategy_images import get_preset_image_path
from universes import FAVORITE_23, IBOVESPA, fetch_all_b3_tickers, universe_text

st.set_page_config(page_title="B3 Strategy Builder", page_icon="📈", layout="wide")

MARKET_TZ = ZoneInfo("America/Sao_Paulo")
MARKET_CLOSE_CUTOFF = time(18, 30)
MARKET_REFERENCE_TICKER = "PETR4"

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

# Menu enxuto: somente os presets priorizados.
PRESETS = [
    "Strategy Builder",
    "Larry Williams — Setup 9.1 Compra",
    "Larry Williams — Setup 9.1 Venda",
    "Price Action — Pivô 1-2-3 Alta",
    "Price Action — Pivô 1-2-3 Baixa",
    "Dave Landry — Compra",
    "Dave Landry — Venda",
]

_EDITOR_OCCURRENCES = {}


def _previous_weekday(day):
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _expected_latest_closed_session(now: datetime):
    if now.weekday() >= 5:
        candidate = now.date()
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate
    if now.time() < MARKET_CLOSE_CUTOFF:
        return _previous_weekday(now.date())
    return now.date()


@st.cache_data(ttl=5 * 60, show_spinner=False)
def market_data_snapshot() -> dict:
    provider = YahooFinanceProvider()
    history = provider.get_history(MARKET_REFERENCE_TICKER, period="1mo")
    latest_date = history.index.max().date()
    checked_at = datetime.now(MARKET_TZ)
    expected_date = _expected_latest_closed_session(checked_at)
    return {
        "latest_date": latest_date,
        "expected_date": expected_date,
        "checked_at": checked_at,
        "is_current": latest_date >= expected_date,
    }


def render_market_data_status(compact: bool = False) -> None:
    try:
        snapshot = market_data_snapshot()
    except Exception as exc:
        if compact:
            st.caption(f"Não foi possível verificar o último pregão disponível agora: {exc}")
        else:
            st.warning("Não foi possível verificar agora a data do último pregão disponível no Yahoo Finance.")
        return

    latest = snapshot["latest_date"].strftime("%d/%m/%Y")
    expected = snapshot["expected_date"].strftime("%d/%m/%Y")
    checked = snapshot["checked_at"].strftime("%H:%M")

    if compact:
        status = "atualizado" if snapshot["is_current"] else f"aguardando referência de {expected}"
        st.caption(
            f"Último pregão diário disponível para análise: **{latest}** · {status} · "
            f"referência {MARKET_REFERENCE_TICKER} · verificado às {checked} BRT."
        )
        return

    st.subheader("Atualização dos dados")
    if snapshot["is_current"]:
        st.success(f"Último pregão diário disponível para análise: {latest}")
    else:
        st.warning(
            f"Último pregão diário disponível para análise: {latest}. "
            f"A referência esperada após o fechamento é {expected}; o Yahoo Finance pode ainda estar atualizando."
        )
    st.caption(
        f"Referência: {MARKET_REFERENCE_TICKER} · Yahoo Finance · verificado às {checked} BRT. "
        "O status é estimado por dias úteis e horário de fechamento; feriados e sessões especiais da B3 podem alterar a referência."
    )


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_all_b3_tickers() -> list[str]:
    return fetch_all_b3_tickers()


def _editor_scope(prefix: str) -> str:
    occurrence = _EDITOR_OCCURRENCES.get(prefix, 0)
    _EDITOR_OCCURRENCES[prefix] = occurrence + 1
    return f"{prefix}__{occurrence}"


def indicator_editor(prefix: str, default_type="IFR (RSI)") -> dict:
    scope = _editor_scope(prefix)
    choice = st.selectbox("Indicador", INDICATORS, index=INDICATORS.index(default_type), key=f"{scope}_kind")

    if choice == "Preço":
        field_label = st.selectbox("Preço", ["Fechamento", "Abertura", "Máxima", "Mínima"], key=f"{scope}_field")
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
        output_label = st.selectbox("Saída", ["Linha MACD", "Linha de sinal", "Histograma"], key=f"{scope}_macd_output")
        output = {"Linha MACD": "macd", "Linha de sinal": "signal", "Histograma": "hist"}[output_label]
        return {"kind": "MACD", "fast": int(fast), "slow": int(slow), "signal": int(signal), "output": output}

    if choice == "Bandas de Bollinger":
        c1, c2 = st.columns(2)
        period = c1.number_input("Período", 2, 300, 20, key=f"{scope}_bb_period")
        std = c2.number_input("Desvios", 0.1, 5.0, 2.0, 0.1, key=f"{scope}_bb_std")
        output_label = st.selectbox("Saída", ["Banda superior", "Média", "Banda inferior", "%B", "Bandwidth"], key=f"{scope}_bb_output")
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
    output_label = st.selectbox("Saída", ["Volume atual", "Média de volume", "Volume / média"], key=f"{scope}_volume_output")
    output = {"Volume atual": "volume", "Média de volume": "average", "Volume / média": "ratio"}[output_label]
    return {"kind": "VOLUME", "period": int(period), "output": output}


def _trend_rules(side: str) -> list[dict]:
    if side == "buy":
        return [
            {"connector": "AND", "left": {"kind": "EMA", "period": 21}, "operator": "rising"},
            {"connector": "AND", "left": {"kind": "EMA", "period": 50}, "operator": "rising"},
            {
                "connector": "AND",
                "left": {"kind": "EMA", "period": 21},
                "operator": ">",
                "right_kind": "indicator",
                "right": {"kind": "EMA", "period": 50},
            },
        ]
    return [
        {"connector": "AND", "left": {"kind": "EMA", "period": 21}, "operator": "falling"},
        {"connector": "AND", "left": {"kind": "EMA", "period": 50}, "operator": "falling"},
        {
            "connector": "AND",
            "left": {"kind": "EMA", "period": 21},
            "operator": "<",
            "right_kind": "indicator",
            "right": {"kind": "EMA", "period": 50},
        },
    ]


def preset_rules(name: str):
    price = {"kind": "PRICE", "field": "Close"}
    ema9 = {"kind": "EMA", "period": 9}

    if name == "IFR2 — Retorno à média em tendência de alta":
        return [
            {"left": {"kind": "RSI", "period": 2}, "operator": "<", "right_kind": "value", "right_value": 5.0},
            {"connector": "AND", "left": {"kind": "EMA", "period": 50}, "operator": "rising"},
            {
                "connector": "AND",
                "left": price,
                "operator": ">",
                "right_kind": "indicator",
                "right": {"kind": "EMA", "period": 50},
            },
        ]

    if name == "Larry Williams — Setup 9.1 Compra":
        return [{"left": ema9, "operator": "setup_91_buy"}, *_trend_rules("buy")]
    if name == "Larry Williams — Setup 9.1 Venda":
        return [{"left": ema9, "operator": "setup_91_sell"}, *_trend_rules("sell")]
    if name == "Larry Williams — Setup 9.2 Compra":
        return [{"left": ema9, "operator": "setup_92_buy"}, *_trend_rules("buy")]
    if name == "Larry Williams — Setup 9.2 Venda":
        return [{"left": ema9, "operator": "setup_92_sell"}, *_trend_rules("sell")]
    if name == "Larry Williams — 9.1 + Estrutura Compra":
        return [{"left": price, "operator": "setup_91_structure_buy"}]
    if name == "Larry Williams — 9.1 + Estrutura Venda":
        return [{"left": price, "operator": "setup_91_structure_sell"}]
    if name == "Dave Landry — Compra":
        return [{"left": price, "operator": "landry_simple_buy"}]
    if name == "Dave Landry — Venda":
        return [{"left": price, "operator": "landry_simple_sell"}]
    if name == "Price Action — Pivô de Alta Simples":
        return [{"left": price, "operator": "simple_pivot_buy"}]
    if name == "Price Action — Pivô de Baixa Simples":
        return [{"left": price, "operator": "simple_pivot_sell"}]
    if name == "Price Action — Pivô 1-2-3 Alta":
        return [{"left": price, "operator": "pivot_123_buy"}]
    if name == "Price Action — Pivô 1-2-3 Baixa":
        return [{"left": price, "operator": "pivot_123_sell"}]
    if name == "Momentum 20/50/80 — Compra":
        return [{"left": price, "operator": "momentum_205080_buy"}]
    if name == "Momentum 20/50/80 — Venda":
        return [{"left": price, "operator": "momentum_205080_sell"}]
    if name == "Price Action — Fundo Duplo":
        return [{"left": price, "operator": "double_bottom"}]
    if name == "Price Action — Topo Duplo":
        return [{"left": price, "operator": "double_top"}]
    if name == "Price Action — OCO Invertido (Compra)":
        return [{"left": price, "operator": "hns_buy"}]
    if name == "Price Action — OCO (Venda)":
        return [{"left": price, "operator": "hns_sell"}]
    if name == "Divergência IFR14 + Estrutura — Compra":
        return [{"left": price, "operator": "divergence_structure_buy"}]
    if name == "Divergência IFR14 + Estrutura — Venda":
        return [{"left": price, "operator": "divergence_structure_sell"}]
    if name == "Price Action — Pivô de Alta / Saída de Consolidação":
        return [{"left": price, "operator": "pivot_breakout_buy"}]
    if name == "Price Action — Pivô de Baixa / Saída de Consolidação":
        return [{"left": price, "operator": "pivot_breakout_sell"}]
    return None


st.title("B3 Strategy Builder")
st.caption("Scanners técnicos focados em tendência/pullback, retorno à média e rompimentos, com Strategy Builder para testes personalizados.")

with st.sidebar:
    st.header("Universo")
    universe_name = st.selectbox(
        "Universo predefinido",
        ["Todos os ativos da B3", "Ativos do Ibovespa", "BDRs", "Meus 23 ativos"],
        index=1,
        key="universe_preset",
    )

    universe_error = None
    selected_tickers = None
    if universe_name == "Todos os ativos da B3":
        try:
            selected_tickers = cached_all_b3_tickers()
        except Exception as exc:
            universe_error = str(exc)
    elif universe_name == "Ativos do Ibovespa":
        selected_tickers = IBOVESPA
    elif universe_name == "BDRs":
        selected_tickers = BDRS
    else:
        selected_tickers = FAVORITE_23

    if selected_tickers is not None:
        if st.session_state.get("_loaded_universe") != universe_name:
            st.session_state["ticker_text"] = universe_text(selected_tickers)
            st.session_state["_loaded_universe"] = universe_name
        st.caption(f"{len(selected_tickers)} ativos carregados. A lista abaixo continua editável.")
        if universe_name == "Todos os ativos da B3":
            st.caption("A lista ampla é atualizada automaticamente; os preços continuam vindo do Yahoo Finance.")
    else:
        st.error("Não foi possível carregar o universo completo da B3 agora.")
        st.caption(universe_error or "Tente novamente em alguns instantes.")
        if "ticker_text" not in st.session_state:
            st.session_state["ticker_text"] = universe_text(IBOVESPA)

    ticker_text = st.text_area(
        "Tickers",
        height=68,
        key="ticker_text",
        help="Você pode editar a lista manualmente depois de carregar qualquer universo.",
    )
    timeframe = st.selectbox("Timeframe", ["Diário", "Semanal", "Mensal"])
    history_period = st.selectbox("Histórico", ["6mo", "1y", "2y", "5y", "10y"], index=2)

    st.divider()
    st.subheader("Estratégia")
    preset = st.selectbox("Atalho / preset", PRESETS)
    context_filters = st.multiselect(
        "Filtros de contexto (opcionais)",
        CONTEXT_FILTERS,
        default=[],
        help="Os filtros são independentes da estratégia e combinados por AND. Use-os para exigir contexto adicional sem criar novos presets.",
    )
    if context_filters:
        st.caption(f"Contexto: {describe_context_filters(context_filters)}")

rules = preset_rules(preset)

if rules is None:
    st.subheader("Construtor de estratégia")
    st.caption("As regras são avaliadas da esquerda para a direita. Cada condição a partir da segunda pode usar AND ou OR.")
    rule_count = st.number_input("Número de condições", min_value=1, max_value=10, value=1, step=1)
    rules = []

    for i in range(int(rule_count)):
        with st.expander(f"Condição {i + 1}", expanded=True):
            if i > 0:
                connector = st.radio(
                    "Conector com a condição anterior",
                    ["AND", "OR"],
                    horizontal=True,
                    key=f"rule_{i}_connector",
                )
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
                compare_with = st.selectbox(
                    "Comparar com",
                    ["Valor fixo", "Preço de fechamento", "Outro indicador"],
                    key=f"rule_{i}_right_kind",
                )
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
    image_path = get_preset_image_path(preset)
    if image_path:
        st.image(image_path, use_container_width=True)

st.subheader("Estratégia atual")
st.code(describe_strategy(rules), language=None)
if context_filters:
    st.markdown(f"**Filtro de contexto:** {describe_context_filters(context_filters)}")

render_market_data_status()
run = st.button("Rodar screener", type="primary", use_container_width=True)

if run:
    raw_tickers = [line.strip().upper().replace(".SA", "") for line in ticker_text.splitlines() if line.strip()]
    tickers = list(dict.fromkeys(raw_tickers))
    if not tickers:
        st.error("Informe pelo menos um ticker.")
        st.stop()
    if len(tickers) > 150:
        st.info(f"Universo amplo selecionado: {len(tickers)} ativos. A consulta ao Yahoo Finance pode levar mais tempo.")

    provider = YahooFinanceProvider()
    with st.spinner(f"Analisando {len(tickers)} ativos..."):
        result, errors = scan_universe(
            tickers,
            provider,
            timeframe,
            history_period,
            rules,
            context_filters=context_filters,
        )

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
            st.info("Nenhum ativo passou pela estratégia e pelos filtros de contexto atuais.")
        else:
            st.dataframe(passed, use_container_width=True, hide_index=True)

        with st.expander("Auditoria — todos os ativos, estratégia e contexto"):
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
render_market_data_status(compact=True)
st.caption("Dados de preço: Yahoo Finance via yfinance. O screener consulta o histórico disponível a cada execução.")