from abc import ABC, abstractmethod

import pandas as pd
import yfinance as yf

from db import is_database_configured, load_history, upsert_prices


def _trim_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df is None or df.empty or period in {"max", None}:
        return df

    days_map = {
        "1mo": 40,
        "3mo": 120,
        "6mo": 230,
        "1y": 400,
        "2y": 800,
        "5y": 1900,
        "10y": 3800,
    }
    days = days_map.get(period)
    if not days:
        return df
    cutoff = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
    return df[df.index >= cutoff]


class MarketDataProvider(ABC):
    @abstractmethod
    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        raise NotImplementedError


class YahooFinanceProvider(MarketDataProvider):
    """
    Fonte externa usada para ingestão/backfill.
    Tickers B3 recebem o sufixo .SA automaticamente.
    """

    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        symbol = ticker if ticker.endswith(".SA") else f"{ticker}.SA"

        df = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if df is None or df.empty:
            raise ValueError("Sem histórico disponível.")

        if isinstance(df.columns, pd.MultiIndex):
            if symbol in df.columns.get_level_values(-1):
                try:
                    df = df.xs(symbol, axis=1, level=-1)
                except Exception:
                    pass

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Colunas ausentes: {', '.join(missing)}")

        keep = required + (["Adj Close"] if "Adj Close" in df.columns else [])
        df = df[keep].copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df.dropna(subset=["Close"])


class PostgresMarketDataProvider(MarketDataProvider):
    """
    Lê do banco próprio. Se um ticker ainda não estiver populado, faz
    backfill via Yahoo, grava no PostgreSQL e devolve o histórico.
    """

    def __init__(self, fallback: MarketDataProvider | None = None):
        self.fallback = fallback or YahooFinanceProvider()

    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        if not is_database_configured():
            return self.fallback.get_history(ticker, period)

        df = load_history(ticker)
        if df is None or df.empty:
            fetched = self.fallback.get_history(ticker, "10y")
            upsert_prices(ticker, fetched, source="yahoo")
            df = load_history(ticker)

        if df is None or df.empty:
            raise ValueError("Sem histórico disponível no banco.")

        return _trim_period(df, period)


def default_market_data_provider() -> MarketDataProvider:
    if is_database_configured():
        return PostgresMarketDataProvider()
    return YahooFinanceProvider()
