from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
import os
import re

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from market_sessions import MARKET_TZ, expected_latest_closed_session


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
            timeout=15,
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
                    threads=4,
                    timeout=15,
                    group_by="ticker",
                )
            except Exception as exc:
                for ticker in chunk:
                    errors[ticker] = str(exc)
                continue

            if len(symbols) == 1:
                ticker = chunk[0]
                try:
                    frame = downloaded
                    symbol = symbols[0]
                    if isinstance(frame.columns, pd.MultiIndex):
                        if symbol in frame.columns.get_level_values(0):
                            frame = frame[symbol]
                        elif symbol in frame.columns.get_level_values(-1):
                            frame = frame.xs(symbol, axis=1, level=-1)
                    histories[ticker] = self._normalize_frame(frame)
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


# The original Yahoo provider remains available to historical backtests.
# Live scans use the independent source first and validate each symbol below.
OHLCV = ["Open", "High", "Low", "Close", "Volume"]
BRAPI_DEMO_TICKERS = frozenset({"PETR4", "VALE3", "ITUB4", "MGLU3"})


def _clean_ticker(ticker: str) -> str:
    symbol = ticker.strip().upper().removesuffix(".SA")
    if not re.fullmatch(r"[A-Z0-9^]{2,12}", symbol):
        raise ValueError("Código de ativo inválido.")
    return symbol


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate complete daily candles; do not fill in missing prices or volume."""
    if frame is None or frame.empty:
        raise ValueError("Sem histórico disponível.")
    if any(column not in frame.columns for column in OHLCV):
        raise ValueError("Histórico sem todas as colunas OHLCV.")
    out = frame[OHLCV].copy().dropna(how="all")
    index = pd.DatetimeIndex(pd.to_datetime(out.index))
    if index.tz is not None:
        index = index.tz_convert(MARKET_TZ).tz_localize(None)
    out.index = index.normalize()
    if out.index.hasnans or out.index.has_duplicates:
        raise ValueError("Datas inválidas ou candles duplicados no histórico.")
    out = out.sort_index().apply(pd.to_numeric, errors="coerce")
    if out.empty or not np.isfinite(out.to_numpy(dtype=float)).all():
        raise ValueError("Candles incompletos ou valores OHLCV inválidos.")
    prices = out[["Open", "High", "Low", "Close"]]
    invalid = (
        (prices <= 0).any(axis=1) | (out["Volume"] < 0)
        | (out["High"] < prices.max(axis=1))
        | (out["Low"] > prices.min(axis=1))
    )
    if invalid.any():
        raise ValueError("Preços ou volume inconsistentes no histórico.")
    return out


def _period_start(period: str, end: date) -> date:
    match = re.fullmatch(r"(\d+)(d|mo|y)", period)
    if not match:
        raise ValueError(f"Período não suportado: {period}.")
    amount, unit = int(match[1]), match[2]
    delta = pd.DateOffset(**{{"d": "days", "mo": "months", "y": "years"}[unit]: amount})
    return (pd.Timestamp(end) - delta).date()


class BrapiProvider(MarketDataProvider):
    """Daily OHLCV from brapi v2; token travels only in the Authorization header."""

    name = "brapi"
    endpoint = "https://brapi.dev/api/v2/stocks/historical"

    def __init__(self, token: str | None = None, session=None):
        self.token = (token if token is not None else os.getenv("BRAPI_TOKEN", "")).strip()
        self.session = session or requests.Session()
        self._blocked_reason = None

    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        symbol = _clean_ticker(ticker)
        if self._blocked_reason:
            raise ValueError(self._blocked_reason)
        if not self.token and symbol not in BRAPI_DEMO_TICKERS:
            raise ValueError("Token brapi necessário para este ativo; configure BRAPI_TOKEN.")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            response = self.session.get(
                self.endpoint,
                params={"symbols": symbol, "range": period, "interval": "1d", "sortOrder": "asc"},
                headers=headers, timeout=(5, 20),
            )
        except requests.RequestException:
            self._blocked_reason = "brapi indisponível ou tempo limite excedido."
            raise ValueError(self._blocked_reason) from None
        try:
            if response.status_code in (401, 403, 429):
                self._blocked_reason = {
                    401: "Token brapi ausente ou inválido.",
                    403: "O plano brapi não permite esta consulta.",
                    429: "Limite de consultas da brapi atingido; tente novamente mais tarde.",
                }[response.status_code]
                raise ValueError(self._blocked_reason)
            if response.status_code != 200:
                reason = f"brapi indisponível (HTTP {response.status_code})."
                if response.status_code >= 500:
                    self._blocked_reason = reason
                raise ValueError(reason)
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Resposta inválida da brapi.") from None
        finally:
            response.close()
        if not isinstance(payload, dict):
            raise ValueError("Resposta inválida da brapi.")
        results = payload.get("results") or []
        item = next((item for item in results if isinstance(item, dict)
                     and item.get("requestedSymbol", item.get("symbol")) == symbol), None)
        if item is None:
            raise ValueError("Ativo ausente na resposta da brapi.")
        data = item.get("data") or {}
        if data.get("usedInterval") != "1d":
            raise ValueError("A brapi não retornou candles diários.")
        used_range = data.get("usedRange")
        if used_range and used_range not in (period, "max"):
            # Plans may silently shorten the requested history (HTTP 200).
            anchor = date(2026, 1, 1)
            if _period_start(used_range, anchor) > _period_start(period, anchor):
                raise ValueError(f"Plano brapi limitou o histórico a {used_range}; solicitado {period}.")
        records = data.get("historicalDataPrice") or []
        if not records:
            raise ValueError("Sem histórico disponível na brapi.")
        frame = pd.DataFrame(records)
        if "date" not in frame:
            raise ValueError("Histórico brapi sem datas.")
        frame.index = pd.to_datetime(frame.pop("date"), unit="s", utc=True).dt.tz_convert(MARKET_TZ)
        frame = frame.rename(columns={name.lower(): name for name in OHLCV})
        # Use one consistent OHLC basis; never replace Close alone with adjustedClose.
        return normalize_ohlcv(frame)

    def get_histories(self, tickers: list[str], period: str = "2y", **kwargs):
        histories, errors = {}, {}
        for ticker in dict.fromkeys(tickers):
            try:
                histories[ticker] = self.get_history(ticker, period)
            except Exception as exc:
                errors[ticker] = str(exc)
        return histories, errors


class ResilientMarketDataProvider(MarketDataProvider):
    """brapi first, Yahoo only for failed/stale symbols; never merge their candles."""

    def __init__(self, token: str | None = None, *, primary=None, fallback=None, now=None):
        self.primary = primary if primary is not None else BrapiProvider(token)
        self.fallback = fallback if fallback is not None else YahooFinanceProvider()
        self.checked_at = now or datetime.now(MARKET_TZ)
        self.expected_date = expected_latest_closed_session(self.checked_at)
        self.diagnostics: dict[str, dict] = {}

    def _validate(self, frame, period, source, detail):
        out = normalize_ohlcv(frame)
        out = out.loc[out.index.date <= self.expected_date].copy()
        if out.empty:
            raise ValueError("Nenhum candle de pregão encerrado disponível.")
        latest = out.index[-1].date()
        detail["latest_date"] = latest
        if latest != self.expected_date:
            raise ValueError(
                f"Dados defasados: último candle {latest:%d/%m/%Y}; "
                f"pregão esperado {self.expected_date:%d/%m/%Y}."
            )
        start = _period_start(period, self.expected_date)
        if out.index[0].date() > start + timedelta(days=14):
            raise ValueError(
                f"Histórico insuficiente para {period}: começa em {out.index[0]:%d/%m/%Y}. "
                "Verifique a cobertura/plano ou a data de listagem do ativo."
            )
        out.attrs.update(source=source, latest_session=latest, expected_session=self.expected_date)
        return out

    @staticmethod
    def _batch(provider, tickers, period):
        try:
            if hasattr(provider, "get_histories"):
                return provider.get_histories(tickers, period=period, chunk_size=10)
            histories, errors = {}, {}
            for ticker in tickers:
                try:
                    histories[ticker] = provider.get_history(ticker, period=period)
                except Exception as exc:
                    errors[ticker] = str(exc)
            return histories, errors
        except Exception:
            return {}, {ticker: "Não foi possível consultar a fonte." for ticker in tickers}

    def get_histories(self, tickers: list[str], period: str = "2y", **kwargs):
        tickers = list(dict.fromkeys(tickers))
        histories, errors = {}, {}
        self.diagnostics = {
            ticker: {"source": None, "latest_date": None, "expected_date": self.expected_date,
                     "status": "Indisponível", "attempts": []}
            for ticker in tickers
        }
        for provider, source in ((self.primary, "brapi"), (self.fallback, "Yahoo Finance")):
            pending = [ticker for ticker in tickers if ticker not in histories]
            if not pending:
                break
            frames, failures = self._batch(provider, pending, period)
            for ticker in pending:
                detail = {"source": source, "latest_date": None, "error": None}
                diagnostic = self.diagnostics[ticker]
                try:
                    if ticker not in frames:
                        raise ValueError(failures.get(ticker, "Sem histórico disponível."))
                    frame = self._validate(frames[ticker], period, source, detail)
                    histories[ticker] = frame
                    diagnostic.update(source=source, latest_date=detail["latest_date"], status="Atualizado")
                except Exception as exc:
                    detail["error"] = str(exc)
                    latest = detail["latest_date"]
                    if latest and (not diagnostic["latest_date"] or latest > diagnostic["latest_date"]):
                        diagnostic.update(source=source, latest_date=latest)
                    if diagnostic["latest_date"]:
                        diagnostic["status"] = (
                            "Defasado" if diagnostic["latest_date"] < self.expected_date else "Histórico inválido"
                        )
                diagnostic["attempts"].append(detail)
        for ticker in tickers:
            if ticker not in histories:
                errors[ticker] = " | ".join(
                    f"{attempt['source']}: {attempt['error']}" for attempt in self.diagnostics[ticker]["attempts"]
                )
        return histories, errors

    def get_history(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        histories, errors = self.get_histories([ticker], period)
        if ticker not in histories:
            raise ValueError(errors[ticker])
        return histories[ticker]
