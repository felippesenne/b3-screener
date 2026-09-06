from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FAVORITE_23 = [
    "AXIA3", "B3SA3", "BBAS3", "BBDC4", "BBSE3", "BPAC11", "CMIG4",
    "CPFE3", "CPLE3", "CSMG3", "CXSE3", "EGIE3", "ISAE4", "ITUB4",
    "PETR4", "PRIO3", "PSSA3", "SANB11", "SBSP3", "TAEE11", "TIMS3",
    "VALE3", "VIVT3",
]


BDRS = [
    "AAPL34", "A1MD34", "A1MT34", "ADBE34", "AIRB34", "AMZO34", "ASML34",
    "ATTB34", "AURA33", "AVGO34", "AXPB34", "BABA34", "C2OI34", "CATP34",
    "CHVX34", "COCA34", "COWC34", "CSCO34", "CTGP34", "D1EL34", "DBAG34",
    "DISB34", "EXXO34", "FCXO34", "GOGL34", "GSGI34", "HOME34", "IBMB34",
    "INBR32", "ITLC34", "JBSS32", "JNJB34", "JPMC34", "LILY34", "M1TA34",
    "M2RV34", "M2ST34", "MCDC34", "MELI34", "MSCD34", "MSFT34", "MUTC34",
    "N1OW34", "N1VO34", "NFLX34", "NIKE34", "NVDC34", "ORCL34", "P2LT34",
    "PAGS34", "PEPB34", "PFIZ34", "PGCO34", "PYPL34", "QCOM34", "RIOT34",
    "ROXO34", "SNEC34", "SPCX34", "SSFO34", "STOC34", "TMOS34", "TSLA34",
    "TSMC34", "U1BE34", "UNHH34", "VISA34", "WALM34", "W1DC34", "XPBR31",
]


IBOVESPA = [
    "ABEV3", "ALOS3", "ASAI3", "AURE3", "AXIA3", "AXIA6", "AZZA3",
    "B3SA3", "BBAS3", "BBDC3", "BBDC4", "BBSE3", "BEEF3", "BPAC11",
    "BRAP4", "BRAV3", "BRKM5", "CEAB3", "CMIG4", "CMIN3", "COGN3",
    "CPFE3", "CPLE3", "CSAN3", "CSMG3", "CSNA3", "CURY3", "CXSE3",
    "CYRE3", "DIRR3", "EGIE3", "EMBJ3", "ENEV3", "ENGI11", "EQTL3",
    "FLRY3", "GGBR4", "GOAU4", "HAPV3", "HYPE3", "IGTI11", "ISAE4",
    "ITSA4", "ITUB4", "KLBN11", "LREN3", "MBRF3", "MGLU3", "MOTV3",
    "MRVE3", "MULT3", "NATU3", "PETR3", "PETR4", "POMO4", "PRIO3",
    "PSSA3", "RADL3", "RAIL3", "RDOR3", "RECV3", "RENT3", "SANB11",
    "SBSP3", "SLCE3", "SMFT3", "SUZB3", "TAEE11", "TIMS3", "TOTS3",
    "UGPA3", "USIM5", "VALE3", "VAMO3", "VBBR3", "VIVA3", "VIVT3",
    "WEGE3", "YDUQ3",
]


BRAPI_LIST_URL = "https://brapi.dev/api/quote/list"


def fetch_all_b3_tickers(timeout: int = 12) -> list[str]:
    """Busca ações e units negociadas na B3 para montar o universo amplo.

    A fonte é usada somente para descobrir os códigos. As séries de preços do
    screener continuam vindo exclusivamente do Yahoo Finance/yfinance.
    """
    tickers: set[str] = set()
    page = 1

    while page <= 50:
        query = urlencode({"type": "stock", "limit": 100, "page": page})
        request = Request(
            f"{BRAPI_LIST_URL}?{query}",
            headers={"User-Agent": "b3-screener/1.0"},
        )
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        stocks = payload.get("stocks") or []
        for item in stocks:
            if not isinstance(item, dict):
                continue
            subtype = str(item.get("subType") or "").strip().lower()
            if subtype and subtype not in {"stock", "unit"}:
                continue
            ticker = str(item.get("stock") or "").strip().upper().replace(".SA", "")
            if ticker and ticker.replace("_", "").isalnum():
                tickers.add(ticker)

        has_next = bool(payload.get("hasNextPage"))
        total_pages = payload.get("totalPages")
        if not has_next and (not total_pages or page >= int(total_pages)):
            break
        page += 1

    # Proteção contra resposta parcial ou mudança de API.
    if len(tickers) < 100:
        raise RuntimeError("A fonte do universo B3 retornou poucos ativos; tente novamente.")

    return sorted(tickers)


def universe_text(tickers: list[str]) -> str:
    return "\n".join(tickers)
