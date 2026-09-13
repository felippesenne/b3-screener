from __future__ import annotations

from collections import defaultdict
from datetime import date

import pandas as pd
import requests

from data_provider import YahooFinanceProvider
from .calculations import normalize_options


class BrapiError(RuntimeError):
    pass


class BrapiOptionsClient:
    BASE_URL = "https://brapi.dev/api/v2/options"

    def __init__(self, token: str | None = None, timeout: float = 20.0):
        self.token = (token or "").strip()
        self.timeout = float(timeout)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def analytics(self, underlying: str, expiration_date: str) -> dict:
        params = {
            "underlying": str(underlying).upper().strip(),
            "expirationDate": str(expiration_date).strip(),
            "limit": 500,
        }
        try:
            response = requests.get(
                f"{self.BASE_URL}/analytics",
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise BrapiError(f"Falha de conexão com a brapi: {exc}") from exc

        if response.status_code == 401:
            raise BrapiError("Token brapi inválido ou ausente.")
        if response.status_code == 403:
            raise BrapiError(
                "A brapi bloqueou a consulta. Para opções fora de PETR4, o endpoint de gregas exige plano Pro/token válido."
            )
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or str(payload)
            except Exception:
                detail = response.text[:300]
            raise BrapiError(f"brapi retornou HTTP {response.status_code}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise BrapiError("Resposta inválida da brapi.") from exc
        if not isinstance(payload, dict):
            raise BrapiError("Formato inesperado na resposta da brapi.")
        return payload


def fetch_stock_quotes(tickers: list[str]) -> tuple[dict[str, float], dict[str, str]]:
    clean = list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))
    if not clean:
        return {}, {}
    provider = YahooFinanceProvider()
    histories, errors = provider.get_histories(clean, period="5d")
    quotes: dict[str, float] = {}
    for ticker, frame in histories.items():
        if frame is None or frame.empty:
            continue
        try:
            quotes[ticker] = float(frame["Close"].dropna().iloc[-1])
        except Exception as exc:
            errors[ticker] = str(exc)
    return quotes, errors


def fetch_option_analytics(
    options: pd.DataFrame | None,
    token: str | None = None,
) -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    """Fetch greeks in batches by (underlying, expiration).

    Returns ``analytics_by_symbol``, ``errors`` and ``source_dates``. The brapi
    analytics endpoint is EOD, so source dates are exposed to the UI rather than
    presenting the values as intraday live data.
    """
    options = normalize_options(options)
    if options.empty:
        return {}, {}, {}

    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    errors: dict[str, str] = {}
    for _, row in options.iterrows():
        status = str(row.get("Status", "")).upper()
        if status.startswith("ENCERR"):
            continue
        symbol = str(row.get("Opção", "")).upper().strip()
        underlying = str(row.get("Ativo base", "")).upper().strip()
        expiry_raw = str(row.get("Vencimento", "")).strip()
        expiry = pd.to_datetime(expiry_raw, errors="coerce")
        if not symbol:
            continue
        if not underlying or pd.isna(expiry):
            errors[symbol] = "Informe Ativo base e Vencimento (YYYY-MM-DD) para buscar delta/gregas."
            continue
        groups[(underlying, expiry.date().isoformat())].append(symbol)

    client = BrapiOptionsClient(token=token)
    analytics_by_symbol: dict[str, dict] = {}
    source_dates: dict[str, str] = {}

    for (underlying, expiry), symbols in groups.items():
        try:
            payload = client.analytics(underlying, expiry)
        except BrapiError as exc:
            for symbol in symbols:
                errors[symbol] = str(exc)
            continue

        source_date = str(payload.get("date") or "")
        rows = payload.get("analytics") or []
        index = {
            str(item.get("symbol", "")).upper(): item
            for item in rows
            if isinstance(item, dict) and item.get("symbol")
        }
        for symbol in symbols:
            item = index.get(symbol)
            if item is None:
                errors[symbol] = f"Série não encontrada na cadeia analítica de {underlying} / {expiry}."
                continue
            analytics_by_symbol[symbol] = item
            source_dates[symbol] = source_date or str(item.get("date") or "")

    return analytics_by_symbol, errors, source_dates
