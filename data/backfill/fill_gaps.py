#!/usr/bin/env python3
"""
Fill Missing Minute Bars
Detects gaps in stock_candles_1m (periods when the collector was down or
internet was interrupted) and fetches the missing data from Alpaca.

Algorithm:
  1. For each trading day in the target range, generate all expected minute
     buckets (4:00 AM – 8:00 PM ET).
  2. Query the DB to see which minute buckets actually have bars.
  3. Any minute with zero symbols reporting = collector was definitely down.
  4. Group consecutive missing minutes into gap windows.
  5. For each window, batch-fetch all symbols from Alpaca and upsert.

Usage:
    python database/fill_gaps.py                         # today only
    python database/fill_gaps.py 2026-02-17              # specific date
    python database/fill_gaps.py 2026-02-10 2026-02-17  # date range
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta, date as date_type
from config import Config
from dotenv import load_dotenv
from utils.trading_calendar import get_trading_days as calendar_trading_days
import pytz
import logging
import time

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

STOCKS_FILE = os.path.join(os.path.dirname(__file__), 'stocks_1_to_20.txt')
BATCH_SIZE  = 500     # symbols per Alpaca API call
MIN_GAP_MINUTES = 2  # ignore single-minute holes (normal for low-volume stocks)

ET  = pytz.timezone('America/New_York')
UTC = pytz.utc

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)-8s] %(message)s')
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_symbols():
    if not os.path.exists(STOCKS_FILE):
        logger.error(f"Symbol file not found: {STOCKS_FILE}")
        return []
    with open(STOCKS_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def get_db():
    logger.info(f"Connecting to database...")
    logger.info(f"  Connection string: {DB_CONN[:50]}...")
    try:
        conn = psycopg2.connect(DB_CONN, connect_timeout=10,
                                options='-c statement_timeout=60000')  # 60s query timeout
        logger.info("  Connected OK")
        return conn
    except Exception as e:
        logger.error(f"  DB connection FAILED: {type(e).__name__}: {e}")
        raise


def get_trading_days(start_date, end_date):
    """
    Return all NYSE trading days in [start_date, end_date] using the
    authoritative market calendar — not by querying what's in the DB.
    This way we catch days that are completely missing (Docker down, etc.).
    """
    logger.info(f"Computing trading days from {start_date} to {end_date}...")
    days = calendar_trading_days(start_date, end_date)
    logger.info(f"  Found {len(days)} trading day(s): {days}")
    return days


def find_gaps(conn, trade_date, symbols):
    """
    Find time windows on trade_date where the collector was down.

    Returns list of (gap_start_utc, gap_end_utc) datetime pairs.
    """
    # Build the expected set of minute buckets (4am-8pm ET)
    day_et_start = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 4, 0))
    day_et_end   = ET.localize(datetime(trade_date.year, trade_date.month, trade_date.day, 20, 0))

    # Don't look beyond now (no future data)
    now_utc = datetime.now(UTC)
    end_cutoff = min(day_et_end.astimezone(UTC), now_utc - timedelta(minutes=2))

    if day_et_start.astimezone(UTC) >= end_cutoff:
        return []  # Day hasn't started yet or too recent

    # Generate every expected minute in UTC
    expected = set()
    t = day_et_start.astimezone(UTC).replace(second=0, microsecond=0)
    while t < end_cutoff:
        expected.add(t)
        t += timedelta(minutes=1)

    # Query which minute buckets actually have any bars
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT date_trunc('minute', time) AS minute_bucket
            FROM stock_candles_1m
            WHERE time >= %s
              AND time < %s
        """, [
            day_et_start.astimezone(UTC),
            day_et_end.astimezone(UTC)
        ])
        present = {row[0].replace(tzinfo=UTC) for row in cur.fetchall()}

    missing = sorted(expected - present)

    if not missing:
        logger.info(f"  {trade_date}: No gaps found ✓")
        return []

    logger.info(f"  {trade_date}: {len(missing)} missing minute(s) out of {len(expected)} expected")

    # Group consecutive missing minutes into windows, ignoring short gaps
    gaps = []
    if missing:
        window_start = missing[0]
        window_end   = missing[0]

        for m in missing[1:]:
            if m - window_end <= timedelta(minutes=1):
                window_end = m
            else:
                if (window_end - window_start).seconds // 60 + 1 >= MIN_GAP_MINUTES:
                    # Add a 1-minute buffer on each side to catch partial bars
                    gaps.append((window_start - timedelta(minutes=1),
                                 window_end + timedelta(minutes=2)))
                window_start = m
                window_end   = m

        # Don't forget the last window
        if (window_end - window_start).seconds // 60 + 1 >= MIN_GAP_MINUTES:
            gaps.append((window_start - timedelta(minutes=1),
                         window_end + timedelta(minutes=2)))

    logger.info(f"  → {len(gaps)} gap window(s) to fill")
    for gs, ge in gaps:
        gs_et = gs.astimezone(ET)
        ge_et = ge.astimezone(ET)
        logger.info(f"      {gs_et.strftime('%H:%M')} – {ge_et.strftime('%H:%M')} ET "
                    f"({int((ge - gs).seconds / 60)} min)")
    return gaps


ALPACA_TIMEOUT = 60  # seconds per batch — longer since fill gaps can cover big windows

def fetch_and_insert(conn, symbols, start_utc, end_utc):
    """
    Fetch minute bars for all symbols in [start_utc, end_utc] from Alpaca
    and upsert into stock_candles_1m.
    Returns number of rows inserted.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)
    batches = [symbols[i:i+BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    logger.info(f"  Alpaca key: ...{Config.ALPACA_API_KEY[-6:] if Config.ALPACA_API_KEY else 'MISSING'}")

    total_inserted = 0
    for batch_num, batch in enumerate(batches, 1):
        try:
            logger.info(f"    Batch {batch_num}/{len(batches)}: calling Alpaca for {len(batch)} symbols...")
            req = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Minute,
                start=start_utc,
                end=end_utc
            )

            # Wrap API call with timeout so it can't hang forever
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(client.get_stock_bars, req)
                resp = future.result(timeout=ALPACA_TIMEOUT)

            logger.info(f"    Batch {batch_num}/{len(batches)}: got data for {len(resp.data)} symbols")

            values = []
            for sym, bars in resp.data.items():
                for bar in bars:
                    values.append((
                        bar.timestamp,
                        sym,
                        float(bar.open),
                        float(bar.high),
                        float(bar.low),
                        float(bar.close),
                        int(bar.volume),
                        int(bar.trade_count) if bar.trade_count else None,
                        float(bar.vwap) if bar.vwap else None
                    ))

            if values:
                with conn.cursor() as cur:
                    execute_values(cur, """
                        INSERT INTO stock_candles_1m
                            (time, symbol, open, high, low, close, volume, trade_count, vwap)
                        VALUES %s
                        ON CONFLICT (time, symbol) DO NOTHING
                    """, values)
                conn.commit()
                total_inserted += len(values)
                logger.info(f"    Batch {batch_num}/{len(batches)}: {len(values):,} bars inserted")
            else:
                logger.info(f"    Batch {batch_num}/{len(batches)}: 0 bars (market may have been closed)")

        except FuturesTimeout:
            logger.error(f"    Batch {batch_num}/{len(batches)}: TIMED OUT after {ALPACA_TIMEOUT}s — Alpaca not responding")
            conn.rollback()
            time.sleep(2)
        except Exception as e:
            logger.warning(f"    Batch {batch_num}/{len(batches)} failed: {type(e).__name__}: {e}")
            conn.rollback()
            time.sleep(2)  # brief pause before next batch

    return total_inserted


# ── Main ───────────────────────────────────────────────────────────────────────

def fill_gaps_for_date(conn, symbols, trade_date):
    """Detect and fill all gaps on a single trading day."""
    logger.info(f"\n{'─'*60}")
    logger.info(f"Checking {trade_date.strftime('%Y-%m-%d (%A)')} ...")

    gaps = find_gaps(conn, trade_date, symbols)
    if not gaps:
        return 0

    total = 0
    for gap_start, gap_end in gaps:
        logger.info(f"  Fetching {gap_start.astimezone(ET).strftime('%H:%M')} – "
                    f"{gap_end.astimezone(ET).strftime('%H:%M')} ET ...")
        inserted = fetch_and_insert(conn, symbols, gap_start, gap_end)
        total += inserted
        if len(gaps) > 1:
            time.sleep(0.5)  # small pause between gap windows

    logger.info(f"  ✅ {total:,} bars recovered for {trade_date}")
    return total


def main():
    today = date_type.today()

    # Parse command-line dates
    if len(sys.argv) == 1:
        start_date = end_date = today
    elif len(sys.argv) == 2:
        start_date = end_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    elif len(sys.argv) == 3:
        start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        end_date   = datetime.strptime(sys.argv[2], '%Y-%m-%d').date()
    else:
        print("Usage: python fill_gaps.py [start_date] [end_date]")
        print("  Dates in YYYY-MM-DD format. Omit for today.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("  MINUTE BAR GAP FILLER")
    logger.info("=" * 60)
    logger.info(f"  Date range : {start_date} → {end_date}")
    logger.info(f"  Gap threshold : {MIN_GAP_MINUTES}+ consecutive missing minutes")

    symbols = load_symbols()
    if not symbols:
        logger.error("No symbols loaded — exiting.")
        return

    logger.info(f"  Symbols : {len(symbols):,}")

    trading_days = get_trading_days(start_date, end_date)
    if not trading_days:
        logger.warning("No trading days in that range (weekends/holidays only).")
        return

    logger.info(f"  Trading days: {trading_days}")

    conn = get_db()
    try:

        grand_total = 0
        for trade_date in trading_days:
            grand_total += fill_gaps_for_date(conn, symbols, trade_date)

        logger.info(f"\n{'='*60}")
        logger.info(f"  DONE — {grand_total:,} total bars recovered across {len(trading_days)} day(s)")
        logger.info(f"{'='*60}")

    finally:
        conn.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Gap fill cancelled by user")
    except Exception as e:
        logger.exception(f"[FATAL] {e}")
