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

navigation = st.navigation([screener_page, eod_page, backtesting_page, portfolio_page])
navigation.run()
