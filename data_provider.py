from abc import ABC, abstractmethod
import pandas as pd
import yfinance as yf


class MarketDataProvider(ABC):
    @abstractmethod
    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        raise NotImplementedError


class YahooFinanceProvider(MarketDataProvider):
    """
    Provider do screener usando Yahoo Finance.
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
                df.columns = [
                    col[0] if isinstance(col, tuple) else col
                    for col in df.columns
                ]

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Colunas ausentes: {', '.join(missing)}")

        df = df[required].copy()
        df.index = pd.to_datetime(df.index)
        df = df.dropna(subset=["Close"])
        return df
