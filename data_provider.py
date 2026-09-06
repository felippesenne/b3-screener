from abc import ABC, abstractmethod

import pandas as pd
import yfinance as yf


class MarketDataProvider(ABC):
    @abstractmethod
    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        raise NotImplementedError


class YahooFinanceProvider(MarketDataProvider):
    """Provider do screener usando Yahoo Finance.

    Tickers B3 recebem o sufixo .SA automaticamente. Para universos grandes,
    o provider também oferece download em lotes para reduzir o tempo total.
    """

    @staticmethod
    def _symbol(ticker: str) -> str:
        return ticker if ticker.endswith(".SA") else f"{ticker}.SA"

    @staticmethod
    def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            raise ValueError("Sem histórico disponível.")

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Colunas ausentes: {', '.join(missing)}")

        out = df[required].copy()
        out.index = pd.to_datetime(out.index)
        out = out.dropna(subset=["Close"])
        if out.empty:
            raise ValueError("Sem histórico disponível.")
        return out

    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        symbol = self._symbol(ticker)
        df = yf.download(
            symbol,
            period=period,
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
        )

        if isinstance(df.columns, pd.MultiIndex):
            if symbol in df.columns.get_level_values(-1):
                try:
                    df = df.xs(symbol, axis=1, level=-1)
                except Exception:
                    pass
            elif symbol in df.columns.get_level_values(0):
                try:
                    df = df[symbol]
                except Exception:
                    pass

        return self._normalize_frame(df)

    def get_histories(
        self,
        tickers: list[str],
        period: str = "2y",
        chunk_size: int = 80,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """Baixa vários ativos em lotes, mantendo falhas isoladas por ticker."""
        histories: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        clean_tickers = list(dict.fromkeys(tickers))

        for start in range(0, len(clean_tickers), chunk_size):
            chunk = clean_tickers[start:start + chunk_size]
            mapping = {ticker: self._symbol(ticker) for ticker in chunk}
            symbols = list(mapping.values())

            try:
                downloaded = yf.download(
                    symbols,
                    period=period,
                    interval="1d",
                    auto_adjust=False,
                    progress=False,
                    threads=True,
                    group_by="ticker",
                )
            except Exception as exc:
                for ticker in chunk:
                    errors[ticker] = str(exc)
                continue

            if len(symbols) == 1:
                ticker = chunk[0]
                try:
                    histories[ticker] = self._normalize_frame(downloaded)
                except Exception as exc:
                    errors[ticker] = str(exc)
                continue

            if downloaded is None or downloaded.empty or not isinstance(downloaded.columns, pd.MultiIndex):
                for ticker in chunk:
                    errors[ticker] = "Sem histórico disponível no download em lote."
                continue

            level0 = set(downloaded.columns.get_level_values(0))
            level_last = set(downloaded.columns.get_level_values(-1))

            for ticker, symbol in mapping.items():
                try:
                    if symbol in level0:
                        frame = downloaded[symbol].copy()
                    elif symbol in level_last:
                        frame = downloaded.xs(symbol, axis=1, level=-1).copy()
                    else:
                        raise ValueError("Ticker ausente no retorno do Yahoo Finance.")
                    histories[ticker] = self._normalize_frame(frame)
                except Exception as exc:
                    errors[ticker] = str(exc)

        return histories, errors
