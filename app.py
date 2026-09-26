import sys

import streamlit as st


# O Streamlit Cloud pode manter módulos Python carregados entre reruns/deploys.
# Se a interface for atualizada antes dos módulos de cálculo, o app pode ficar
# numa combinação incompatível (por exemplo, Screener novo + indicators antigo).
# Removemos toda a cadeia principal do screener antes de abrir a página para que
# ela seja importada novamente, de forma consistente, a partir do código atual.
SCREENER_RUNTIME_MODULES = (
    "universes",
    "market_sessions",
    "data_provider",
    "indicators",
    "trade_de_valor_setups",
    "structure_setups",
    "classic_setups",
    "scanner",
    "strategy_images",
)
for module_name in SCREENER_RUNTIME_MODULES:
    sys.modules.pop(module_name, None)


# O nome usado nas listas do app é IBOV, mas no Yahoo Finance o índice Ibovespa
# é ^BVSP. Mantemos o rótulo amigável no app e traduzimos somente na camada de
# acesso ao Yahoo. A classe é importada novamente acima em cada rerun/deploy.
import data_provider  # noqa: E402

_original_yahoo_symbol = data_provider.YahooFinanceProvider._symbol


def _yahoo_symbol_with_indices(ticker: str) -> str:
    clean = str(ticker).strip().upper()
    if clean in {"IBOV", "^BVSP"}:
        return "^BVSP"
    return _original_yahoo_symbol(clean)


data_provider.YahooFinanceProvider._symbol = staticmethod(_yahoo_symbol_with_indices)


screener_page = st.Page(
    "pages/Screener.py",
    title="Screener",
    icon="📈",
    default=True,
)
backtesting_page = st.Page(
    "pages/1_Backtesting.py",
    title="Backtesting",
    icon="🧪",
)
portfolio_page = st.Page(
    "pages/2_Carteira.py",
    title="Carteira",
    icon="💼",
)
eod_page = st.Page(
    "pages/3_Checklist_EOD.py",
    title="Checklist EOD",
    icon="✅",
)
yahoo_audit_page = st.Page(
    "pages/4_Auditoria_Yahoo.py",
    title="Auditoria Yahoo",
    icon="🔎",
)

navigation = st.navigation([
    screener_page,
    eod_page,
    backtesting_page,
    portfolio_page,
    yahoo_audit_page,
])
navigation.run()
