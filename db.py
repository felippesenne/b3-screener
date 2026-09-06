import os
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, MetaData, String, Table, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

metadata = MetaData()

market_prices = Table(
    "market_prices",
    metadata,
    Column("ticker", String(32), primary_key=True),
    Column("date", Date, primary_key=True),
    Column("open", Float, nullable=False),
    Column("high", Float, nullable=False),
    Column("low", Float, nullable=False),
    Column("close", Float, nullable=False),
    Column("adj_close", Float),
    Column("volume", BigInteger),
    Column("source", String(32), nullable=False, default="yahoo"),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

tracked_tickers = Table(
    "tracked_tickers",
    metadata,
    Column("ticker", String(32), primary_key=True),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

data_updates = Table(
    "data_updates",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("status", String(32), nullable=False),
    Column("tickers_total", BigInteger, nullable=False, default=0),
    Column("tickers_ok", BigInteger, nullable=False, default=0),
    Column("rows_upserted", BigInteger, nullable=False, default=0),
    Column("latest_market_date", Date),
    Column("message", String(500)),
)


def database_url() -> str | None:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL")
    except Exception:
        return None


def is_database_configured() -> bool:
    return bool(database_url())


def get_engine():
    url = database_url()
    if not url:
        raise RuntimeError("DATABASE_URL não configurada.")
    return create_engine(url, pool_pre_ping=True, future=True)


def init_db() -> None:
    metadata.create_all(get_engine())


def normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().replace(".SA", "")


def ensure_tracked_tickers(tickers: Iterable[str]) -> None:
    normalized = sorted({normalize_ticker(t) for t in tickers if str(t).strip()})
    if not normalized:
        return
    init_db()
    now = datetime.now(timezone.utc)
    rows = [{"ticker": t, "active": True, "created_at": now} for t in normalized]
    stmt = pg_insert(tracked_tickers).values(rows)
    stmt = stmt.on_conflict_do_update(index_elements=[tracked_tickers.c.ticker], set_={"active": True})
    with get_engine().begin() as conn:
        conn.execute(stmt)


def list_tracked_tickers(active_only: bool = True) -> list[str]:
    init_db()
    stmt = select(tracked_tickers.c.ticker)
    if active_only:
        stmt = stmt.where(tracked_tickers.c.active.is_(True))
    stmt = stmt.order_by(tracked_tickers.c.ticker)
    with get_engine().connect() as conn:
        return [row[0] for row in conn.execute(stmt).all()]


def upsert_prices(ticker: str, df: pd.DataFrame, source: str = "yahoo") -> int:
    if df is None or df.empty:
        return 0

    init_db()
    ticker = normalize_ticker(ticker)
    now = datetime.now(timezone.utc)
    rows = []
    for idx, row in df.iterrows():
        date_value = pd.Timestamp(idx).date()
        close = row.get("Close")
        if pd.isna(close):
            continue
        rows.append({
            "ticker": ticker,
            "date": date_value,
            "open": float(row.get("Open", close)),
            "high": float(row.get("High", close)),
            "low": float(row.get("Low", close)),
            "close": float(close),
            "adj_close": None if pd.isna(row.get("Adj Close")) else float(row.get("Adj Close")),
            "volume": None if pd.isna(row.get("Volume")) else int(row.get("Volume")),
            "source": source,
            "updated_at": now,
        })

    if not rows:
        return 0

    stmt = pg_insert(market_prices).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[market_prices.c.ticker, market_prices.c.date],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
            "volume": stmt.excluded.volume,
            "source": stmt.excluded.source,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)
    return len(rows)


def load_history(ticker: str) -> pd.DataFrame:
    init_db()
    ticker = normalize_ticker(ticker)
    stmt = select(
        market_prices.c.date,
        market_prices.c.open,
        market_prices.c.high,
        market_prices.c.low,
        market_prices.c.close,
        market_prices.c.adj_close,
        market_prices.c.volume,
    ).where(market_prices.c.ticker == ticker).order_by(market_prices.c.date)

    with get_engine().connect() as conn:
        rows = conn.execute(stmt).mappings().all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).rename(columns={
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adj_close": "Adj Close",
        "volume": "Volume",
    })
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


def latest_price_date(ticker: str):
    init_db()
    stmt = select(text("MAX(date)")).select_from(market_prices).where(market_prices.c.ticker == normalize_ticker(ticker))
    with get_engine().connect() as conn:
        return conn.execute(stmt).scalar_one_or_none()


def database_status() -> dict:
    if not is_database_configured():
        return {"configured": False}

    init_db()
    with get_engine().connect() as conn:
        latest_date = conn.execute(select(text("MAX(date)")).select_from(market_prices)).scalar_one_or_none()
        price_rows = conn.execute(select(text("COUNT(*)")).select_from(market_prices)).scalar_one()
        ticker_count = conn.execute(select(text("COUNT(*)")).select_from(tracked_tickers).where(tracked_tickers.c.active.is_(True))).scalar_one()
        last_update = conn.execute(text("""
            SELECT started_at, finished_at, status, tickers_total, tickers_ok,
                   rows_upserted, latest_market_date, message
            FROM data_updates
            ORDER BY id DESC
            LIMIT 1
        """)).mappings().first()

    return {
        "configured": True,
        "latest_market_date": latest_date,
        "price_rows": int(price_rows or 0),
        "tracked_tickers": int(ticker_count or 0),
        "last_update": dict(last_update) if last_update else None,
    }


def start_update_run(tickers_total: int) -> int:
    init_db()
    stmt = data_updates.insert().values(
        started_at=datetime.now(timezone.utc),
        status="running",
        tickers_total=tickers_total,
        tickers_ok=0,
        rows_upserted=0,
    ).returning(data_updates.c.id)
    with get_engine().begin() as conn:
        return int(conn.execute(stmt).scalar_one())


def finish_update_run(run_id: int, *, status: str, tickers_ok: int, rows_upserted: int, latest_market_date=None, message: str | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            data_updates.update().where(data_updates.c.id == run_id).values(
                finished_at=datetime.now(timezone.utc),
                status=status,
                tickers_ok=tickers_ok,
                rows_upserted=rows_upserted,
                latest_market_date=latest_market_date,
                message=(message or "")[:500],
            )
        )
