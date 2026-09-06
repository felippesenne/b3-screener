import sys
from pathlib import Path

from data_provider import YahooFinanceProvider
from db import (
    ensure_tracked_tickers,
    finish_update_run,
    init_db,
    latest_price_date,
    list_tracked_tickers,
    start_update_run,
    upsert_prices,
)

SEED_FILE = Path(__file__).with_name("universe_b3.txt")


def seed_universe_if_needed() -> list[str]:
    tracked = list_tracked_tickers()
    if tracked:
        return tracked

    tickers = []
    if SEED_FILE.exists():
        tickers = [
            line.strip().upper().replace(".SA", "")
            for line in SEED_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    if not tickers:
        raise RuntimeError("Nenhum ticker configurado para atualização.")

    ensure_tracked_tickers(tickers)
    return list_tracked_tickers()


def main() -> int:
    init_db()
    tickers = seed_universe_if_needed()
    run_id = start_update_run(len(tickers))
    provider = YahooFinanceProvider()

    ok = 0
    rows_total = 0
    max_date = None
    errors = []

    for ticker in tickers:
        try:
            existing_latest = latest_price_date(ticker)
            period = "10y" if existing_latest is None else "3mo"
            df = provider.get_history(ticker, period=period)
            rows_total += upsert_prices(ticker, df, source="yahoo")
            latest = df.index.max().date() if not df.empty else existing_latest
            if latest and (max_date is None or latest > max_date):
                max_date = latest
            ok += 1
            print(f"[OK] {ticker}: {len(df)} candles; última data {latest}")
        except Exception as exc:
            msg = f"{ticker}: {exc}"
            errors.append(msg)
            print(f"[ERRO] {msg}", file=sys.stderr)

    status = "success" if ok == len(tickers) else ("partial" if ok else "failed")
    message = "; ".join(errors[:5])
    if len(errors) > 5:
        message += f"; +{len(errors) - 5} erros"

    finish_update_run(
        run_id,
        status=status,
        tickers_ok=ok,
        rows_upserted=rows_total,
        latest_market_date=max_date,
        message=message,
    )

    print(
        f"Atualização concluída: status={status}, "
        f"tickers={ok}/{len(tickers)}, linhas={rows_total}, data-base={max_date}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
