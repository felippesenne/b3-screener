"""B3 sessions, using the exchange calendar rather than weekday guesses."""
from datetime import datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

MARKET_TZ = ZoneInfo("America/Sao_Paulo")
# Conservative cutoff: never use the still-forming daily candle.
MARKET_CLOSE_CUTOFF = time(18, 30)


@lru_cache(maxsize=4)
def _calendar(year: int):
    return xcals.get_calendar("BVMF", start=f"{year - 1}-01-01", end=f"{year + 1}-12-31")


def expected_latest_closed_session(now: datetime | None = None):
    now = now or datetime.now(MARKET_TZ)
    local = now.replace(tzinfo=MARKET_TZ) if now.tzinfo is None else now.astimezone(MARKET_TZ)
    candidate = local.date()
    if local.time() < MARKET_CLOSE_CUTOFF:
        candidate -= timedelta(days=1)
    return _calendar(local.year).date_to_session(candidate.isoformat(), direction="previous").date()
