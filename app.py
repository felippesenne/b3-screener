import sys

import streamlit as st


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

# O Streamlit Cloud mantém módulos Python carregados entre alguns reruns.
# Quando universes.py e Screener.py mudam no mesmo deploy, uma versão antiga
# de `universes` pode permanecer em sys.modules e causar ImportError para
# constantes recém-adicionadas. Força uma importação fresca antes de abrir a página.
sys.modules.pop("universes", None)

navigation.run()
