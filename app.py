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

navigation = st.navigation([screener_page, backtesting_page])
navigation.run()
