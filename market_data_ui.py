"""Shared Streamlit controls for current B3 scans (not historical backtests)."""
import os

import pandas as pd
import streamlit as st

from market_sessions import expected_latest_closed_session


def configured_brapi_token() -> str:
    token = os.getenv("BRAPI_TOKEN", "").strip()
    if token:
        return token
    try:
        return str(st.secrets.get("BRAPI_TOKEN", "")).strip()
    except (FileNotFoundError, KeyError):
        return ""


def brapi_token() -> str:
    return configured_brapi_token() or st.session_state.get("brapi_token", "")


def _save_session_token():
    st.session_state["brapi_token"] = st.session_state.get("_brapi_token_input", "").strip()


def render_data_source_settings():
    with st.sidebar.expander("Fonte de dados", expanded=not bool(brapi_token())):
        st.caption("Fonte principal: brapi. Reserva automática: Yahoo Finance.")
        if configured_brapi_token():
            st.caption("Token brapi configurado no servidor.")
        else:
            st.text_input(
                "Token brapi", type="password", key="_brapi_token_input",
                value=st.session_state.get("brapi_token", ""), on_change=_save_session_token,
                help="Usado apenas nesta sessão. Para manter a configuração, salve BRAPI_TOKEN nos Secrets do Streamlit.",
            )
        if not brapi_token():
            st.warning(
                "Sem token, a brapi libera apenas PETR4, VALE3, ITUB4 e MGLU3. "
                "Os demais ativos dependem da reserva Yahoo."
            )
            st.markdown("[Obter token na brapi](https://brapi.dev/dashboard)")
        st.caption("A cobertura e o tamanho do histórico dependem do plano da brapi.")


def render_market_data_status():
    expected = expected_latest_closed_session()
    st.subheader("Atualização dos dados")
    st.caption(
        f"Pregão encerrado esperado: {expected:%d/%m/%Y}. Ao rodar, cada ativo será verificado "
        "individualmente. Dados defasados ou incompletos ficam fora dos sinais."
    )
    st.caption(
        "Somente candles diários encerrados; corte conservador às 18h30 de Brasília, "
        "considerando o calendário da B3."
    )


def render_data_audit(provider):
    rows = []
    for ticker, detail in provider.diagnostics.items():
        latest = detail.get("latest_date")
        rows.append({
            "Ticker": ticker,
            "Fonte": detail.get("source") or "—",
            "Último pregão disponível": latest.strftime("%d/%m/%Y") if latest else "—",
            "Pregão esperado": detail["expected_date"].strftime("%d/%m/%Y"),
            "Situação dos dados": detail["status"],
            "Observação": " | ".join(
                f"{attempt['source']}: {attempt['error']}"
                for attempt in detail["attempts"] if attempt.get("error")
            ),
        })
    if not rows:
        return
    blocked = sum(row["Situação dos dados"] != "Atualizado" for row in rows)
    if blocked:
        st.warning(f"{blocked} de {len(rows)} ativos excluídos por dados indisponíveis, defasados ou incompletos.")
    else:
        st.success(f"Os {len(rows)} ativos têm dados até {provider.expected_date:%d/%m/%Y}.")
    with st.expander("Atualização por ativo — fonte, data e falhas", expanded=bool(blocked)):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
