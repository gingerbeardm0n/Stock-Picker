#!/usr/bin/env python3
"""
Historical Tradable Stocks — Per-Day Accurate Price Filtering
=============================================================
For each trading day in a date range, determines which stocks were priced
between $1-$20 and stores the result in tradable_stocks_by_date.

Three modes:
  --from-db   Use closing prices already in stock_candles_1d (fastest — no API
              calls for dates already backfilled). Best for dates you've already
              collected daily bar data for.

  --polygon   Fetch from Polygon API (free tier, 5 calls/min). Uses grouped
              daily endpoint to get ALL stocks' OHLCV in one call per date.

  (default)   Fetch daily bars from Alpaca for each date. Accurate back to 2016.
              Uses TimeFrame.Day with start=date, end=date — NOT the snapshot
              endpoint (which only returns current prices).

Usage:
  # Populate from existing daily bars already in the DB (fast, no API calls):
  python research/database_analysis/historical_tradable_stocks.py --start 2023-01-01 --end 2024-12-31 --from-db

  # Fetch from Polygon API (efficient, free tier):
  python research/database_analysis/historical_tradable_stocks.py --start 2026-03-16 --end 2026-03-25 --polygon

  # Fetch from Alpaca API (use when daily bars not yet in DB):
  python research/database_analysis/historical_tradable_stocks.py --start 2023-01-01 --end 2024-12-31

  # Skip dates already populated:
  python research/database_analysis/historical_tradable_stocks.py --start 2023-01-01 --end 2024-12-31 --skip-existing

  # Last 30 trading days via API:
  python research/database_analysis/historical_tradable_stocks.py --days 30
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env.paper'))

import logging
import argparse
import time
import requests
import json
from datetime import datetime, timedelta, date as date_type
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from config import Config
from utils.query_helpers import StockDataDB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

MIN_PRICE = 1.0
MAX_PRICE = 20.0
BATCH_SIZE = 1000   # symbols per Alpaca API call

# Polygon configuration (free tier: 5 calls/min)
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', '')
POLYGON_BASE = 'https://api.polygon.io'
POLYGON_SLEEP = 12  # seconds between calls (5 calls/min = 1 call per 12 sec)


def get_trading_days(start_date: date_type, end_date: date_type) -> list[date_type]:
    """Return weekday dates between start_date and end_date inclusive."""
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def init_database():
    """Create tradable_stocks_by_date table if not exists."""
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tradable_stocks_by_date (
                date   DATE        NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                price  DECIMAL(8, 2) NOT NULL,
                PRIMARY KEY (date, symbol)
            );
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tradable_stocks_date
            ON tradable_stocks_by_date(date);
        """)
        db.conn.commit()
        logger.info("Table tradable_stocks_by_date ready")


def get_covered_dates() -> set[date_type]:
    """Return set of dates that already have at least one row in tradable_stocks_by_date."""
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("SELECT DISTINCT date FROM tradable_stocks_by_date")
        return {row[0] for row in cursor.fetchall()}


def get_all_tradable_symbols() -> list[str]:
    """
    Fetch the full universe of active US equity symbols from Alpaca once.
    This list is stable (exchange membership doesn't change daily) so we
    only need to call it once per run.
    """
    # Try Alpaca Trading API first, fall back to NASDAQ trader FTP
    try:
        logger.info("Fetching full symbol universe from Alpaca (one-time call)...")
        client = TradingClient(
            Config.ALPACA_API_KEY,
            Config.ALPACA_SECRET_KEY,
            paper=(Config.TRADING_MODE == 'PAPER'),
        )
        assets = client.get_all_assets()
        tradable = [
            a.symbol for a in assets
            if a.tradable
            and a.status == 'active'
            and a.exchange in ('NASDAQ', 'NYSE', 'ARCA', 'AMEX')
            and a.asset_class == 'us_equity'
        ]
        logger.info(f"Universe: {len(tradable):,} symbols (Alpaca)")
        return tradable
    except Exception as e:
        logger.warning(f"Alpaca assets fetch failed: {e}")
        logger.info("Falling back to NASDAQ trader FTP for symbol universe...")
        try:
            r = requests.get('https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt', timeout=15)
            r.raise_for_status()
            lines = r.text.strip().split('\n')
            symbols = []
            for line in lines[1:-1]:
                parts = line.split('|')
                if len(parts) < 8:
                    continue
                sym = parts[1]
                is_etf = parts[5] == 'Y'
                is_test = parts[7] == 'Y'
                if (not is_etf and not is_test and sym and ' ' not in sym
                        and '$' not in sym and '.' not in sym and len(sym) <= 5):
                    symbols.append(sym)
            logger.info(f"Universe: {len(symbols):,} symbols (NASDAQ FTP)")
            return symbols
        except Exception as e2:
            logger.error(f"NASDAQ FTP also failed: {e2}")
            return []


def fetch_price_range_from_api(
    all_symbols: list[str],
    target_date: date_type,
) -> list[tuple[str, float]]:
    """
    Use Alpaca daily bars to find which symbols closed between $1-$20
    on target_date.  Returns list of (symbol, close_price) tuples.

    Batches symbols in groups of BATCH_SIZE to stay within API limits.
    Symbols that did not trade on target_date are simply absent from the
    response — no error, just silently skipped.
    """
    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
    )

    # Alpaca end is exclusive for daily bars — add 1 day so target_date is included
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt   = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

    results: list[tuple[str, float]] = []
    total_batches = (len(all_symbols) - 1) // BATCH_SIZE + 1

    for batch_idx, offset in enumerate(range(0, len(all_symbols), BATCH_SIZE), 1):
        chunk = all_symbols[offset : offset + BATCH_SIZE]

        try:
            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Day,
                start=start_dt,
                end=end_dt,
            )
            response = client.get_stock_bars(request)

            for symbol, bars in response.data.items():
                if not bars:
                    continue
                close = float(bars[-1].close)   # last bar of the day
                if MIN_PRICE <= close <= MAX_PRICE:
                    results.append((symbol, round(close, 2)))

        except Exception as e:
            logger.warning(f"  Batch {batch_idx}/{total_batches} failed: {e}")

        time.sleep(0.2)   # ~5 calls/sec, well within 200 req/min limit

    return results


def fetch_price_range_from_db(target_date: date_type) -> list[tuple[str, float]]:
    """
    Use closing prices already in stock_candles_1d to determine which
    symbols were $1-$20 on target_date.  No API calls needed.

    Returns list of (symbol, close_price) tuples, or empty list if
    stock_candles_1d has no data for that date.
    """
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT symbol, close
            FROM   stock_candles_1d
            WHERE  time::date = %s
              AND  close >= %s
              AND  close <= %s
            ORDER BY symbol
        """, (target_date, MIN_PRICE, MAX_PRICE))
        rows = cursor.fetchall()

    return [(row[0], round(float(row[1]), 2)) for row in rows]


def polygon_get(url, params=None):
    """
    GET a Polygon endpoint. Handles 429 rate limit with backoff.
    Returns JSON dict or None on failure.
    """
    p = dict(params or {})
    p['apiKey'] = POLYGON_API_KEY
    for attempt in range(3):
        try:
            resp = requests.get(url, params=p, timeout=30)
            if resp.status_code == 429:
                logger.warning(f'  [429] Rate limited — waiting 65s...')
                time.sleep(65)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning(f'  [ERROR] {e}')
            if attempt < 2:
                time.sleep(5)
    return None


def fetch_price_range_from_polygon(target_date: date_type) -> list[tuple[str, float]]:
    """
    Use Polygon grouped daily endpoint to find which symbols closed between $1-$20
    on target_date.  Returns list of (symbol, close_price) tuples.

    The grouped endpoint returns ALL US stocks' OHLCV for a given date in ONE call.
    This is far more efficient than querying per-symbol like Alpaca requires.
    Free tier: 5 calls/min (12 sec between calls).
    """
    url = f"{POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/{target_date.strftime('%Y-%m-%d')}"

    data = polygon_get(url, {'adjusted': 'true'})
    if not data or 'results' not in data:
        logger.debug(f"  No data from Polygon for {target_date}")
        return []

    results: list[tuple[str, float]] = []
    for bar in data['results']:
        symbol = bar.get('T')
        close = bar.get('c')

        if symbol and close is not None:
            close = float(close)
            if MIN_PRICE <= close <= MAX_PRICE:
                results.append((symbol, round(close, 2)))

    return results


def store_stocks_for_date(target_date: date_type, stocks: list[tuple[str, float]]):
    """
    Replace all rows for target_date in tradable_stocks_by_date with the
    correct historically-accurate list.  DELETE first so stale rows from
    any previous static seed are fully removed before the new data is inserted.
    """
    if not stocks:
        return

    with StockDataDB() as db:
        cursor = db.conn.cursor()
        from psycopg2.extras import execute_values

        # Remove any previously seeded (possibly wrong) rows for this date
        cursor.execute(
            "DELETE FROM tradable_stocks_by_date WHERE date = %s",
            (target_date,)
        )

        execute_values(
            cursor,
            """
            INSERT INTO tradable_stocks_by_date (date, symbol, price)
            VALUES %s
            """,
            [(target_date, sym, price) for sym, price in stocks],
            page_size=5_000,
        )
        db.conn.commit()


def main():
    parser = argparse.ArgumentParser(
        description='Build per-day accurate tradable_stocks_by_date table.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fastest — use daily bars already in stock_candles_1d (no API calls):
  python research/database_analysis/historical_tradable_stocks.py \\
      --start 2023-01-01 --end 2024-12-31 --from-db

  # Fetch from Alpaca API (for dates not yet in DB):
  python research/database_analysis/historical_tradable_stocks.py \\
      --start 2023-01-01 --end 2024-12-31

  # Skip dates already in tradable_stocks_by_date:
  python research/database_analysis/historical_tradable_stocks.py \\
      --start 2023-01-01 --end 2024-12-31 --skip-existing
        """
    )
    parser.add_argument('--start', metavar='YYYY-MM-DD',
                        help='Start date (inclusive)')
    parser.add_argument('--end',   metavar='YYYY-MM-DD',
                        help='End date (inclusive, defaults to today)')
    parser.add_argument('--days',  type=int, metavar='N',
                        help='Last N calendar days (overrides --start/--end)')
    parser.add_argument('--from-db', action='store_true',
                        help='Use stock_candles_1d instead of API calls')
    parser.add_argument('--polygon', action='store_true',
                        help='Use Polygon API (free tier, efficient grouped endpoint)')
    parser.add_argument('--skip-existing', action='store_true',
                        help='Skip dates already populated in tradable_stocks_by_date')
    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("  HISTORICAL TRADABLE STOCKS — PER-DAY PRICE FILTERING")
    print("=" * 70)

    init_database()

    # ── Resolve date range ─────────────────────────────────────────────────────
    today = datetime.now().date()
    if args.days:
        end_date   = today
        start_date = today - timedelta(days=int(args.days * 1.5))
    elif args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        end_date   = datetime.strptime(args.end,   '%Y-%m-%d').date() if args.end else today
    else:
        parser.print_help()
        return

    trading_days = get_trading_days(start_date, end_date)
    logger.info(f"Date range: {start_date} → {end_date}  ({len(trading_days)} trading days)")

    # ── Filter already-covered dates ───────────────────────────────────────────
    if args.skip_existing:
        covered = get_covered_dates()
        before  = len(trading_days)
        trading_days = [d for d in trading_days if d not in covered]
        logger.info(f"Skipping {before - len(trading_days)} dates already in DB "
                    f"({len(trading_days)} remaining)")

    if not trading_days:
        logger.info("Nothing to process.")
        return

    # ── Validate Polygon API key if needed ────────────────────────────────────────
    if args.polygon and not POLYGON_API_KEY:
        logger.error("ERROR: POLYGON_API_KEY not set in .env.paper")
        return

    # ── Preflight test for Polygon mode ────────────────────────────────────────────
    if args.polygon:
        logger.info("Testing Polygon API connection...")
        test_data = polygon_get(f"{POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/2026-03-25",
                                {'adjusted': 'true'})
        if not test_data:
            logger.error("ERROR: Polygon API test failed — check API key and connectivity")
            return
        logger.info(f"  ✓ Polygon API connected")

    # ── API mode: fetch symbol universe once (Alpaca only) ─────────────────────────
    all_symbols: list[str] = []
    if not args.from_db and not args.polygon:
        all_symbols = get_all_tradable_symbols()

    # ── Main loop ──────────────────────────────────────────────────────────────────
    total = len(trading_days)
    total_stored = 0

    for idx, target_date in enumerate(trading_days, 1):
        logger.info(f"[{idx}/{total}] {target_date.strftime('%Y-%m-%d %A')}")

        try:
            if args.from_db:
                stocks = fetch_price_range_from_db(target_date)
                if not stocks:
                    logger.debug(f"  No daily bar data in DB for {target_date} — skipping")
                    continue
                logger.info(f"  {len(stocks):,} symbols in ${MIN_PRICE:.0f}-${MAX_PRICE:.0f} "
                            f"range (from DB)")
            elif args.polygon:
                stocks = fetch_price_range_from_polygon(target_date)
                logger.info(f"  {len(stocks):,} symbols in ${MIN_PRICE:.0f}-${MAX_PRICE:.0f} "
                            f"range (from Polygon)")
                time.sleep(POLYGON_SLEEP)  # Rate limit: 5 calls/min
            else:
                stocks = fetch_price_range_from_api(all_symbols, target_date)
                logger.info(f"  {len(stocks):,} symbols in ${MIN_PRICE:.0f}-${MAX_PRICE:.0f} "
                            f"range (from Alpaca API)")

            store_stocks_for_date(target_date, stocks)
            total_stored += len(stocks)

        except Exception as e:
            logger.error(f"  Failed for {target_date}: {e}")
            continue

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  COMPLETE")
    print("=" * 70)
    logger.info(f"Processed {total} trading days, stored {total_stored:,} symbol-date rows")

    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT date), COUNT(*) FROM tradable_stocks_by_date")
        date_count, total_rows = cursor.fetchone()
        logger.info(f"tradable_stocks_by_date now covers {date_count} days / {total_rows:,} rows total")
    print("=" * 70)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Cancelled by user")
    except Exception as e:
        logger.error(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
