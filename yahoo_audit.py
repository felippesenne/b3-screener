from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import pandas as pd
import requests

from data_provider import YahooFinanceProvider
from market_sessions import MARKET_TZ, expected_latest_closed_session


YAHOO_CHART_HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart",
    "https://query2.finance.yahoo.com/v8/finance/chart",
)


@dataclass
class EndpointResult:
    host: str
    url: str
    http_status: int | None
    latest_date: object | None
    rows: int
    error: str | None
    meta: dict[str, Any]


def normalize_tickers(text: str) -> list[str]:
    raw = text.replace(";", ",").replace("\n", ",").split(",")
    tickers = []
    for item in raw:
        ticker = item.strip().upper().removesuffix(".SA")
        if ticker and ticker not in tickers:
            tickers.append(ticker)
    return tickers


def yahoo_symbol(ticker: str) -> str:
    ticker = ticker.strip().upper()
    return ticker if ticker.endswith(".SA") else f"{ticker}.SA"


def chart_url(ticker: str, period: str = "1mo", host: str = YAHOO_CHART_HOSTS[1]) -> str:
    params = {
        "range": period,
        "interval": "1d",
        "includePrePost": "false",
        "events": "div,splits,capitalGains",
    }
    return f"{host}/{yahoo_symbol(ticker)}?{urlencode(params)}"


def parse_chart_payload(payload: dict[str, Any]) -> tuple[object | None, int, dict[str, Any], str | None]:
    try:
        chart = payload.get("chart") or {}
        error = chart.get("error")
        if error:
            description = error.get("description") if isinstance(error, dict) else str(error)
            return None, 0, {}, description or "Erro retornado pelo Yahoo Finance."
        results = chart.get("result") or []
        if not results:
            return None, 0, {}, "Resposta sem dados de histórico."
        result = results[0]
        timestamps = result.get("timestamp") or []
        meta = result.get("meta") or {}
        if not timestamps:
            return None, 0, meta, "Resposta sem timestamps de candles."
        index = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(MARKET_TZ)
        return index[-1].date(), len(index), meta, None
    except Exception as exc:
        return None, 0, {}, f"Resposta inválida: {exc}"


def fetch_chart_endpoint(
    ticker: str,
    period: str,
    host: str,
    *,
    timeout: int = 15,
    session: requests.Session | None = None,
) -> EndpointResult:
    url = chart_url(ticker, period=period, host=host)
    client = session or requests.Session()
    headers = {
        "Accept": "application/json,text/plain,*/*",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/153 Safari/537.36",
    }
    response = None
    try:
        response = client.get(url, headers=headers, timeout=timeout)
        status = response.status_code
        if status != 200:
            return EndpointResult(host, url, status, None, 0, f"HTTP {status}", {})
        try:
            payload = response.json()
        except ValueError:
            return EndpointResult(host, url, status, None, 0, "Resposta não-JSON.", {})
        latest, rows, meta, error = parse_chart_payload(payload)
        return EndpointResult(host, url, status, latest, rows, error, meta)
    except requests.RequestException as exc:
        return EndpointResult(host, url, None, None, 0, str(exc), {})
    finally:
        if response is not None:
            response.close()
        if session is None:
            client.close()


def _frame_info(frame: pd.DataFrame | None, error: str | None = None) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"latest_date": None, "rows": 0, "error": error or "Sem dados.", "tail": None}
    return {
        "latest_date": pd.Timestamp(frame.index.max()).date(),
        "rows": len(frame),
        "error": error,
        "tail": frame.tail(5).copy(),
    }


def diagnose_ticker(
    expected_date,
    individual: dict[str, Any],
    batch: dict[str, Any],
    endpoints: list[EndpointResult],
) -> str:
    individual_date = individual.get("latest_date")
    batch_date = batch.get("latest_date")
    endpoint_dates = [item.latest_date for item in endpoints if item.latest_date is not None]
    freshest_endpoint = max(endpoint_dates) if endpoint_dates else None

    if individual_date == expected_date and batch_date == expected_date:
        if freshest_endpoint in (None, expected_date):
            return "OK: yfinance individual e lote estão no pregão esperado."
        if freshest_endpoint and freshest_endpoint > expected_date:
            return "Endpoint direto tem candle mais recente que o pregão encerrado esperado."

    if individual_date == expected_date and batch_date != expected_date:
        return "Download em lote está divergente; consulta individual está atualizada."

    if batch_date == expected_date and individual_date != expected_date:
        return "Consulta individual está divergente; download em lote está atualizado."

    if freshest_endpoint == expected_date and individual_date != expected_date:
        return "Endpoint direto está atualizado, mas o yfinance individual está defasado."

    if freshest_endpoint == expected_date and batch_date != expected_date:
        return "Endpoint direto está atualizado, mas o yfinance em lote está defasado."

    observed = [d for d in [individual_date, batch_date, freshest_endpoint] if d is not None]
    if observed and max(observed) < expected_date:
        return "Todas as rotas consultadas estão defasadas neste servidor."

    if not observed:
        return "Não foi possível obter histórico por nenhuma rota testada."

    if len(set(observed)) > 1:
        return "Há discrepância entre as rotas do Yahoo/yfinance."

    return "Dados disponíveis, mas não coincidem com o pregão esperado."


def run_yahoo_audit(tickers: list[str], period: str = "1mo") -> dict[str, Any]:
    provider = YahooFinanceProvider()
    checked_at = datetime.now(MARKET_TZ)
    expected_date = expected_latest_closed_session(checked_at)

    clean_tickers = list(dict.fromkeys(t.strip().upper().removesuffix(".SA") for t in tickers if t.strip()))
    batch_frames, batch_errors = provider.get_histories(
        clean_tickers,
        period=period,
        chunk_size=max(1, len(clean_tickers)),
    )

    details: dict[str, Any] = {}
    rows = []

    for ticker in clean_tickers:
        try:
            individual_frame = provider.get_history(ticker, period=period)
            individual = _frame_info(individual_frame)
        except Exception as exc:
            individual = _frame_info(None, str(exc))

        batch = _frame_info(batch_frames.get(ticker), batch_errors.get(ticker))
        endpoint_results = [fetch_chart_endpoint(ticker, period, host) for host in YAHOO_CHART_HOSTS]
        diagnosis = diagnose_ticker(expected_date, individual, batch, endpoint_results)

        details[ticker] = {
            "individual": individual,
            "batch": batch,
            "endpoints": endpoint_results,
            "diagnosis": diagnosis,
        }

        row = {
            "Ticker": ticker,
            "Pregão esperado": expected_date,
            "yfinance individual": individual["latest_date"],
            "yfinance lote": batch["latest_date"],
            "query1 direto": endpoint_results[0].latest_date,
            "query2 direto": endpoint_results[1].latest_date,
            "HTTP query1": endpoint_results[0].http_status,
            "HTTP query2": endpoint_results[1].http_status,
            "Diagnóstico": diagnosis,
        }
        rows.append(row)

    summary = pd.DataFrame(rows)
    return {
        "checked_at": checked_at,
        "expected_date": expected_date,
        "period": period,
        "summary": summary,
        "details": details,
    }
