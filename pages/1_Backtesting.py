from __future__ import annotations

import json
import math

import pandas as pd
import streamlit as st

from bdr_universe import BDRS
from backtest.ui_helpers import (
    EXIT_LABELS,
    SETUP_LABELS,
    finite_or_none,
    run_setup_backtest_from_history,
    setup_side,
    summary_row,
)
from data_provider import YahooFinanceProvider
from universes import FAVORITE_23, IBOVESPA, fetch_all_b3_tickers


st.set_page_config(page_title="B3 Backtesting Lab", page_icon="🧪", layout="wide")


@st.cache_data(ttl=30 * 60, show_spinner=False)
def cached_history(ticker: str, period: str) -> pd.DataFrame:
    return YahooFinanceProvider().get_history(ticker, period=period)


@st.cache_data(ttl=30 * 60, show_spinner=False)
def cached_histories(tickers: tuple[str, ...], period: str):
    return YahooFinanceProvider().get_histories(list(tickers), period=period)


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def cached_all_b3_tickers() -> list[str]:
    return fetch_all_b3_tickers()


def clean_tickers(text: str) -> list[str]:
    parts = text.replace(",", "\n").replace(";", "\n").splitlines()
    values = [p.strip().upper().replace(".SA", "") for p in parts if p.strip()]
    return list(dict.fromkeys(values))


def fmt_metric(value, suffix: str = "") -> str:
    value = finite_or_none(value)
    if value is None:
        return "—"
    return f"{value:,.2f}{suffix}".replace(",", "X").replace(".", ",").replace("X", ".")


def render_single(ticker: str, df: pd.DataFrame, orders: pd.DataFrame, result, capital: float):
    metrics = result.metrics
    st.subheader(f"Resultado — {ticker}")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Retorno", fmt_metric(metrics.get("total_return_pct"), "%"))
    c2.metric("CAGR", fmt_metric(metrics.get("cagr_pct"), "%"))
    c3.metric("Drawdown máx.", fmt_metric(metrics.get("max_drawdown_pct"), "%"))
    c4.metric("Sharpe", fmt_metric(metrics.get("sharpe")))
    c5.metric("Trades", int(metrics.get("trades", 0)))
    c6.metric("Win rate", fmt_metric(metrics.get("win_rate_pct"), "%"))

    c7, c8, c9, c10 = st.columns(4)
    c7.metric("Profit factor", fmt_metric(metrics.get("profit_factor")))
    c8.metric("Payoff", fmt_metric(metrics.get("payoff")))
    c9.metric("Expectância", f"R$ {fmt_metric(metrics.get('expectancy'))}")
    c10.metric("Equity final", f"R$ {fmt_metric(metrics.get('final_equity'))}")

    strategy = result.equity_curve["Equity"].astype(float) / float(capital) * 100.0
    buy_hold = df["Close"].astype(float) / float(df["Close"].iloc[0]) * 100.0
    comparison = pd.DataFrame({"Estratégia": strategy, "Buy & Hold": buy_hold}).dropna()
    st.markdown("#### Curva normalizada (base 100)")
    st.line_chart(comparison, use_container_width=True)

    drawdown = result.equity_curve["Equity"].astype(float)
    drawdown = (drawdown / drawdown.cummax() - 1.0) * 100.0
    st.markdown("#### Drawdown (%)")
    st.line_chart(drawdown.rename("Drawdown %"), use_container_width=True)

    tab_trades, tab_orders, tab_equity = st.tabs(["Operações", "Ordens do setup", "Equity curve"])
    with tab_trades:
        if result.trades.empty:
            st.info("Nenhuma operação foi executada no período selecionado.")
        else:
            st.dataframe(result.trades, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar operações (CSV)",
                result.trades.to_csv(index=False).encode("utf-8"),
                file_name=f"{ticker}_trades.csv",
                mime="text/csv",
                key=f"download_trades_{ticker}",
            )
    with tab_orders:
        if orders.empty:
            st.info("Nenhuma ordem de entrada foi gerada pelo setup.")
        else:
            st.dataframe(orders, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar ordens (CSV)",
                orders.to_csv(index=False).encode("utf-8"),
                file_name=f"{ticker}_orders.csv",
                mime="text/csv",
                key=f"download_orders_{ticker}",
            )
    with tab_equity:
        st.dataframe(result.equity_curve, use_container_width=True)
        st.download_button(
            "Baixar equity curve (CSV)",
            result.equity_curve.to_csv().encode("utf-8"),
            file_name=f"{ticker}_equity.csv",
            mime="text/csv",
            key=f"download_equity_{ticker}",
        )


st.title("B3 Backtesting Lab")
st.caption(
    "Backtesting orientado a eventos para setups com gatilho real. Ordens são executadas sem look-ahead, "
    "com slippage, custos, gaps e stop técnico do setup."
)

with st.sidebar:
    st.header("Teste")
    mode = st.radio("Modo", ["Ativo individual", "Universo"], horizontal=True)
    setup_label = st.selectbox("Estratégia", list(SETUP_LABELS.keys()))
    setup_id = SETUP_LABELS[setup_label]
    side = setup_side(setup_id)
    st.caption(f"Direção: {'Compra / Long' if side == 'long' else 'Venda / Short'}")

    timeframe = st.selectbox("Timeframe", ["Diário", "Semanal", "Mensal"], index=0)
    period = st.selectbox("Histórico", ["1y", "2y", "5y", "10y", "max"], index=2)
    exit_label = st.selectbox("Saída", EXIT_LABELS, index=0)

    st.divider()
    st.subheader("Capital e execução")
    capital = st.number_input("Capital inicial (R$)", min_value=1_000.0, value=100_000.0, step=10_000.0)
    position_pct = st.slider("Capital por operação (%)", 1, 100, 100) / 100.0
    commission_bps = st.number_input("Custos totais por ordem (bps)", min_value=0.0, value=0.0, step=0.5)
    slippage_bps = st.number_input("Slippage (bps)", min_value=0.0, value=0.0, step=0.5)

    use_target = st.toggle("Usar alvo percentual", value=False)
    target_pct = None
    if use_target:
        target_value = st.number_input("Alvo (%)", min_value=0.1, value=10.0, step=0.5)
        target_pct = float(target_value) / 100.0
    st.caption("O stop de proteção é o stop técnico definido pelo próprio setup.")

    with st.expander("Parâmetros avançados"):
        tick_size = st.number_input("Tick do gatilho (R$)", min_value=0.0, value=0.01, step=0.01, format="%.2f")
        landry_valid_bars = st.number_input("Landry Simple — validade do gatilho (candles)", min_value=1, max_value=20, value=1)
        bowtie_transition_bars = st.number_input("Bow Tie — janela da transição (candles)", min_value=1, max_value=10, value=4)
        same_bar_label = st.selectbox(
            "Ambiguidade intrabar",
            ["Conservador (cancelamento/stop prevalece)", "Gatilho prevalece"],
            index=0,
        )
        same_bar_policy = "conservative" if same_bar_label.startswith("Conservador") else "trigger_first"

    st.divider()
    if mode == "Ativo individual":
        ticker = st.text_input("Ticker", value="PETR4").strip().upper().replace(".SA", "")
        tickers = [ticker] if ticker else []
    else:
        universe_name = st.selectbox(
            "Universo",
            ["Ativos do Ibovespa", "Meus 23 ativos", "BDRs", "Todos os ativos da B3", "Personalizado"],
            index=1,
        )
        if universe_name == "Ativos do Ibovespa":
            tickers = list(IBOVESPA)
        elif universe_name == "Meus 23 ativos":
            tickers = list(FAVORITE_23)
        elif universe_name == "BDRs":
            tickers = list(BDRS)
        elif universe_name == "Todos os ativos da B3":
            try:
                all_tickers = cached_all_b3_tickers()
            except Exception as exc:
                st.error(f"Falha ao carregar o universo B3: {exc}")
                all_tickers = []
            limit = st.number_input("Limite de ativos", min_value=10, max_value=1000, value=150, step=10)
            tickers = list(all_tickers[: int(limit)])
        else:
            custom = st.text_area("Tickers", value="PETR4\nVALE3\nITUB4\nBBAS3", height=120)
            tickers = clean_tickers(custom)
        st.caption(f"{len(tickers)} ativos selecionados.")

    run = st.button("Executar backtest", type="primary", use_container_width=True)

st.info(
    "Premissas: dados OHLCV do Yahoo Finance; execução por OHLC; quando a sequência intrabar é desconhecida, "
    "o modo conservador evita assumir a sequência mais favorável. Universos atuais (ex.: Ibovespa atual) "
    "podem introduzir survivorship bias em testes históricos."
)

if run:
    if not tickers:
        st.error("Selecione pelo menos um ticker.")
        st.stop()

    kwargs = dict(
        setup_id=setup_id,
        timeframe=timeframe,
        capital=float(capital),
        position_size_pct=float(position_pct),
        commission_bps=float(commission_bps),
        slippage_bps=float(slippage_bps),
        take_profit_pct=target_pct,
        exit_label=exit_label,
        tick_size=float(tick_size),
        landry_valid_bars=int(landry_valid_bars),
        bowtie_transition_bars=int(bowtie_transition_bars),
        same_bar_policy=same_bar_policy,
    )

    if mode == "Ativo individual":
        current = tickers[0]
        try:
            with st.spinner(f"Executando {setup_label} em {current}..."):
                raw = cached_history(current, period)
                df, orders, result = run_setup_backtest_from_history(raw, **kwargs)
            render_single(current, df, orders, result, float(capital))
        except Exception as exc:
            st.error(f"Não foi possível executar o backtest de {current}: {exc}")
    else:
        st.subheader("Resultado do universo")
        st.caption(
            "Cada ativo é testado separadamente com o mesmo capital inicial. O ranking abaixo não representa um portfólio agregado."
        )
        try:
            with st.spinner(f"Baixando histórico de {len(tickers)} ativos..."):
                histories, download_errors = cached_histories(tuple(tickers), period)
        except Exception as exc:
            st.error(f"Falha no download em lote: {exc}")
            st.stop()

        rows = []
        errors = dict(download_errors)
        progress = st.progress(0.0)
        status = st.empty()
        total = max(len(tickers), 1)

        for idx, current in enumerate(tickers, start=1):
            status.caption(f"Processando {current} ({idx}/{len(tickers)})")
            raw = histories.get(current)
            if raw is None or raw.empty:
                errors.setdefault(current, "Sem histórico disponível.")
                progress.progress(idx / total)
                continue
            try:
                _, orders, result = run_setup_backtest_from_history(raw, **kwargs)
                rows.append(summary_row(current, result, len(orders)))
            except Exception as exc:
                errors[current] = str(exc)
            progress.progress(idx / total)

        status.empty()
        progress.empty()

        if not rows:
            st.warning("Nenhum ativo pôde ser testado com os parâmetros atuais.")
        else:
            summary = pd.DataFrame(rows)
            summary = summary.sort_values(["Retorno %", "Profit factor"], ascending=[False, False], na_position="last").reset_index(drop=True)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Ativos testados", len(summary))
            c2.metric("Com trades", int((summary["Trades"] > 0).sum()))
            c3.metric("Retorno mediano", fmt_metric(summary["Retorno %"].median(), "%"))
            c4.metric("Win rate mediano", fmt_metric(summary["Win rate %"].median(), "%"))

            st.markdown("#### Ranking")
            st.dataframe(summary, use_container_width=True, hide_index=True)

            chart = summary[summary["Trades"] > 0].head(20).set_index("Ticker")["Retorno %"]
            if not chart.empty:
                st.markdown("#### Top 20 por retorno")
                st.bar_chart(chart, use_container_width=True)

            st.download_button(
                "Baixar ranking (CSV)",
                summary.to_csv(index=False).encode("utf-8"),
                file_name="b3_backtest_ranking.csv",
                mime="text/csv",
            )

        if errors:
            with st.expander(f"Falhas / dados indisponíveis ({len(errors)})"):
                for name, message in errors.items():
                    st.write(f"**{name}:** {message}")

st.divider()
st.caption(
    "B3 Backtesting Lab · V1. Resultados históricos não garantem desempenho futuro. "
    "Antes de usar uma estratégia, valide robustez, custos, liquidez e vieses de seleção."
)
