#!/usr/bin/env python3
"""
Optimized Historical Data Backfill with Hybrid Time-Window Filtering
Collects the data needed for accurate Ross Cameron relative volume calculation:
- 1-minute bars: 8am-12pm (full trading morning, precise signals)
- Hour bars: 4am-8am (premarket session, low noise)
- Daily bars: for volume calculations

For 4,000 stocks over 12 months (252 trading days):
- 1-min storage: ~50 GB (240 bars/day × 4000 × 252 days)
- Hour storage: ~25 GB (4 bars/day × 4000 × 252 days)
- Daily storage: ~5 GB (252 bars × 4000 symbols)
- ON CONFLICT DO NOTHING: safe to re-run, won't duplicate existing data

Usage:
    # Backfill a specific date range:
    python production/data/backfill/backfill_optimized.py --start 2023-01-01 --end 2024-12-31

    # Backfill last N calendar days from today:
    python production/data/backfill/backfill_optimized.py --days 90

    # Interactive menu (no flags):
    python production/data/backfill/backfill_optimized.py

Prerequisites:
    tradable_stocks_by_date must be populated for the date range.
    Run first: python research/database_analysis/historical_tradable_stocks.py --start 2023-01-01 --end 2024-12-31
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta, date as date_type
from config import Config
from dotenv import load_dotenv
from utils.query_helpers import StockDataDB
import json
import logging
import time
import pytz

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

# Progress tracking
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), 'backfill_optimized_progress.json')

# Trading hours in ET
ET = pytz.timezone('US/Eastern')

# Premarket: hour bars (lower noise, adequate for EMA seeding)
HOUR_WINDOW_START = 4   # 4am ET
HOUR_WINDOW_END   = 8   # 8am ET

# Trading morning: 1-minute bars (precise signals for entry/exit)
ONEMIN_WINDOW_START = 8    # 8am ET
ONEMIN_WINDOW_END   = 12   # 12pm ET (noon)

# Flush accumulated bars to DB every N days to keep RAM under control.
# At ~200k bars/day for 3000 symbols, 20 days ≈ 4M rows ≈ ~1 GB peak RAM.
FLUSH_EVERY = 20


def get_trading_days(start_date: date_type, end_date: date_type) -> list[date_type]:
    """Return list of weekday dates between start_date and end_date inclusive."""
    days = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # Monday–Friday
            days.append(current)
        current += timedelta(days=1)
    return days


def load_progress():
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {
        'completed_windows': [],
        'failed_batches': [],
        'total_inserted': 0,
        'last_updated': None,
        'last_heartbeat': None,
    }

def save_progress(progress):
    """Save progress to file + update heartbeat timestamp."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    progress['last_updated'] = now
    progress['last_heartbeat'] = now
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def print_status(start_date=None, end_date=None):
    """
    Print a human-readable status report from the progress file.
    Pass start/end to also show what percentage of a planned range is done.
    """
    progress = load_progress()

    dates_1min = progress.get('completed_dates_1min', [])
    dates_hour = progress.get('completed_dates_hour', [])
    last_heartbeat = progress.get('last_heartbeat') or progress.get('last_updated')
    total_inserted = progress.get('total_inserted', 0)

    print("\n" + "=" * 60)
    print("  BACKFILL STATUS")
    print("=" * 60)

    # Heartbeat / alive check
    if last_heartbeat:
        from datetime import datetime as _dt
        try:
            hb = _dt.strptime(last_heartbeat, '%Y-%m-%d %H:%M:%S')
            age_min = (_dt.now() - hb).total_seconds() / 60
            alive = "✅ LIKELY RUNNING" if age_min < 10 else (
                    "⚠️  STALLED?" if age_min < 60 else "❌ PROBABLY STOPPED")
            print(f"  Last heartbeat : {last_heartbeat}  ({age_min:.0f} min ago)  {alive}")
        except ValueError:
            print(f"  Last heartbeat : {last_heartbeat}")
    else:
        print("  Last heartbeat : never (not started)")

    print(f"  Total rows DB  : {total_inserted:,}")
    print()

    # 1-min progress
    if dates_1min:
        print(f"  1-MIN bars  : {len(dates_1min)} days completed")
        print(f"    First : {dates_1min[0]}")
        print(f"    Last  : {dates_1min[-1]}")
    else:
        print("  1-MIN bars  : 0 days completed")

    # Hour progress
    if dates_hour:
        print(f"  HOUR bars   : {len(dates_hour)} days completed")
        print(f"    First : {dates_hour[0]}")
        print(f"    Last  : {dates_hour[-1]}")
    else:
        print("  HOUR bars   : 0 days completed")

    # Coverage vs planned range
    if start_date and end_date:
        from datetime import date as _date
        s = _date.fromisoformat(str(start_date))
        e = _date.fromisoformat(str(end_date))
        planned = get_trading_days(s, e)
        planned_set = {str(d) for d in planned}
        done_1min = len([d for d in dates_1min if d in planned_set])
        done_hour = len([d for d in dates_hour if d in planned_set])
        total = len(planned)
        pct_1min = done_1min / total * 100 if total else 0
        pct_hour = done_hour / total * 100 if total else 0
        print()
        print(f"  Range coverage ({start_date} to {end_date},  {total} trading days):")
        print(f"    1-min : {done_1min}/{total}  ({pct_1min:.1f}%)")
        print(f"    hour  : {done_hour}/{total}  ({pct_hour:.1f}%)")
        # Find first missing date for each type
        done_1min_set = set(dates_1min)
        done_hour_set = set(dates_hour)
        missing_1min = [d for d in planned if str(d) not in done_1min_set]
        missing_hour = [d for d in planned if str(d) not in done_hour_set]
        if missing_1min:
            print(f"    Next 1-min needed : {missing_1min[0]}")
        if missing_hour:
            print(f"    Next hour  needed : {missing_hour[0]}")

    print("=" * 60 + "\n")

def reset_progress():
    """Clear progress file"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        logger.info("Progress file cleared")

def load_symbols_from_file(filepath):
    """Load symbols from JSON or TXT file"""
    if filepath.endswith('.json'):
        with open(filepath, 'r') as f:
            data = json.load(f)
            return data.get('symbols_only', [])
    else:  # .txt
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]


def _flush_to_db(cursor, conn, values: list, table: str) -> int:
    """Insert accumulated bar rows and return count inserted."""
    if not values:
        return 0
    execute_values(
        cursor,
        f"""
        INSERT INTO {table}
            (time, symbol, open, high, low, close, volume, trade_count, vwap)
        VALUES %s
        ON CONFLICT (time, symbol) DO NOTHING
        """,
        values,
        page_size=10_000,
    )
    conn.commit()
    return len(values)


def backfill_1min_bars_trading(trading_days: list[date_type], batch_num, total_batches, progress):
    """
    Backfill 1-minute bars for 8am-12pm trading window.
    Flushes to DB every FLUSH_EVERY days to keep RAM bounded.
    Tracks completed dates individually so restarts resume mid-range.
    """
    # Skip days already completed in a previous run
    completed_dates = set(progress.get('completed_dates_1min', []))
    remaining = [d for d in trading_days if str(d) not in completed_dates]

    if not remaining:
        logger.info("[SKIP] All 1-min days already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"1-MINUTE BARS (8am-12pm Trading) - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")
    logger.info(f"{len(remaining)} days to process "
                f"({len(completed_dates)} already done, skipped)")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    conn   = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    pending      = []   # bars accumulated since last flush
    total_inserted = 0
    total_api_calls = 0

    try:
        for idx, current_date in enumerate(remaining):
            start_dt = ET.localize(datetime.combine(
                current_date,
                datetime.min.time().replace(hour=ONEMIN_WINDOW_START)
            ))
            end_dt = ET.localize(datetime.combine(
                current_date,
                datetime.min.time().replace(hour=ONEMIN_WINDOW_END)
            ))

            # Get symbol list for this day
            try:
                with StockDataDB() as db:
                    db_cursor = db.conn.cursor()
                    db_cursor.execute(
                        "SELECT symbol FROM tradable_stocks_by_date WHERE date = %s ORDER BY symbol",
                        (current_date,)
                    )
                    symbols_for_day = [row[0] for row in db_cursor.fetchall()]
                    db_cursor.close()
            except Exception as db_error:
                logger.warning(f"  [WARN] DB error for {current_date}: {db_error}")
                continue

            if not symbols_for_day:
                logger.debug(f"  [SKIP] No symbols for {current_date}")
                continue

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=symbols_for_day,
                    timeframe=TimeFrame.Minute,
                    start=start_dt,
                    end=end_dt,
                )
                bars_response = client.get_stock_bars(request)
                total_api_calls += 1

                for symbol, bars in bars_response.data.items():
                    for bar in bars:
                        pending.append((
                            bar.timestamp, symbol,
                            float(bar.open), float(bar.high),
                            float(bar.low),  float(bar.close),
                            int(bar.volume),
                            int(bar.trade_count) if bar.trade_count else None,
                            float(bar.vwap) if bar.vwap else None,
                        ))

                time.sleep(0.5)

            except Exception as day_error:
                logger.warning(f"  [WARN] Failed to fetch {current_date}: {day_error}")
                continue

            # Mark this date done and flush every FLUSH_EVERY days
            progress.setdefault('completed_dates_1min', []).append(str(current_date))

            days_since_flush = (idx + 1) % FLUSH_EVERY
            is_last = (idx == len(remaining) - 1)

            if days_since_flush == 0 or is_last:
                n = _flush_to_db(cursor, conn, pending, 'stock_candles_1m')
                total_inserted += n
                pending = []
                save_progress(progress)
                logger.info(f"  [{idx+1}/{len(remaining)}] Flushed {n:,} bars to DB "
                            f"| total={total_inserted:,} | api_calls={total_api_calls}")

            elif (idx + 1) % 5 == 0:
                logger.info(f"  [{idx+1}/{len(remaining)}] {len(pending):,} bars pending "
                            f"| api_calls={total_api_calls}")
                save_progress(progress)  # heartbeat every 5 days

        cursor.close()
        conn.close()

        progress['total_inserted'] = progress.get('total_inserted', 0) + total_inserted
        progress['completed_windows'].append(f"1min_8to12_batch_{batch_num}")
        save_progress(progress)

        logger.info(f"[SUCCESS] 1-min bars done: {total_inserted:,} rows inserted")
        return total_inserted

    except Exception as e:
        logger.error(f"[ERROR] 1-min backfill failed: {e}")
        # Flush whatever we have before giving up
        try:
            n = _flush_to_db(cursor, conn, pending, 'stock_candles_1m')
            total_inserted += n
            logger.info(f"  Emergency flush: {n:,} bars saved before exit")
        except Exception:
            pass
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass
        save_progress(progress)
        return total_inserted


def backfill_hour_bars(trading_days: list[date_type], batch_num, total_batches, progress):
    """
    Backfill hour bars for 4am-8am premarket window.
    Flushes to DB every FLUSH_EVERY days to keep RAM bounded.
    Tracks completed dates individually so restarts resume mid-range.
    """
    completed_dates = set(progress.get('completed_dates_hour', []))
    remaining = [d for d in trading_days if str(d) not in completed_dates]

    if not remaining:
        logger.info("[SKIP] All hour-bar days already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"HOUR BARS (4am-8am premarket) - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")
    logger.info(f"{len(remaining)} days to process "
                f"({len(completed_dates)} already done, skipped)")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    conn   = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    pending        = []
    total_inserted = 0
    total_api_calls = 0

    try:
        for idx, current_date in enumerate(remaining):
            start_dt = ET.localize(datetime.combine(
                current_date,
                datetime.min.time().replace(hour=HOUR_WINDOW_START)
            ))
            end_dt = ET.localize(datetime.combine(
                current_date,
                datetime.min.time().replace(hour=HOUR_WINDOW_END)
            ))

            try:
                with StockDataDB() as db:
                    db_cursor = db.conn.cursor()
                    db_cursor.execute(
                        "SELECT symbol FROM tradable_stocks_by_date WHERE date = %s ORDER BY symbol",
                        (current_date,)
                    )
                    symbols_for_day = [row[0] for row in db_cursor.fetchall()]
                    db_cursor.close()
            except Exception as db_error:
                logger.warning(f"  [WARN] DB error for {current_date}: {db_error}")
                continue

            if not symbols_for_day:
                logger.debug(f"  [SKIP] No symbols for {current_date}")
                continue

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=symbols_for_day,
                    timeframe=TimeFrame.Hour,
                    start=start_dt,
                    end=end_dt,
                )
                bars_response = client.get_stock_bars(request)
                total_api_calls += 1

                for symbol, bars in bars_response.data.items():
                    for bar in bars:
                        pending.append((
                            bar.timestamp, symbol,
                            float(bar.open), float(bar.high),
                            float(bar.low),  float(bar.close),
                            int(bar.volume),
                            int(bar.trade_count) if bar.trade_count else None,
                            float(bar.vwap) if bar.vwap else None,
                        ))

                time.sleep(0.5)

            except Exception as day_error:
                logger.warning(f"  [WARN] Failed to fetch {current_date}: {day_error}")
                continue

            progress.setdefault('completed_dates_hour', []).append(str(current_date))

            days_since_flush = (idx + 1) % FLUSH_EVERY
            is_last = (idx == len(remaining) - 1)

            if days_since_flush == 0 or is_last:
                n = _flush_to_db(cursor, conn, pending, 'stock_candles_1h')
                total_inserted += n
                pending = []
                save_progress(progress)
                logger.info(f"  [{idx+1}/{len(remaining)}] Flushed {n:,} bars to DB "
                            f"| total={total_inserted:,} | api_calls={total_api_calls}")

            elif (idx + 1) % 5 == 0:
                logger.info(f"  [{idx+1}/{len(remaining)}] {len(pending):,} bars pending "
                            f"| api_calls={total_api_calls}")
                save_progress(progress)  # heartbeat every 5 days

        cursor.close()
        conn.close()

        progress['total_inserted'] = progress.get('total_inserted', 0) + total_inserted
        progress['completed_windows'].append(f"hour_allday_batch_{batch_num}")
        save_progress(progress)

        logger.info(f"[SUCCESS] Hour bars done: {total_inserted:,} rows inserted")
        return total_inserted

    except Exception as e:
        logger.error(f"[ERROR] Hour backfill failed: {e}")
        try:
            n = _flush_to_db(cursor, conn, pending, 'stock_candles_1h')
            total_inserted += n
            logger.info(f"  Emergency flush: {n:,} bars saved before exit")
        except Exception:
            pass
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass
        save_progress(progress)
        return total_inserted



def backfill_daily_bars(symbols, trading_days: list[date_type], batch_num, total_batches, progress):
    """Backfill daily bars for volume calculations"""

    window_key = f"daily_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"DAILY BARS - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    start = datetime.combine(trading_days[0], datetime.min.time())
    end   = datetime.combine(trading_days[-1], datetime.min.time()) + timedelta(days=1)

    try:
        batch_start = time.time()

        logger.info(f"Fetching daily bars for {len(symbols):,} symbols "
                    f"({trading_days[0]} -> {trading_days[-1]})...")
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Day,
            start=start,
            end=end
        )

        bars_response = client.get_stock_bars(request)
        fetch_time = time.time() - batch_start
        logger.info(f"API call completed in {fetch_time:.1f}s")

        conn = psycopg2.connect(DB_CONN)
        cursor = conn.cursor()

        values = []
        for symbol, bars in bars_response.data.items():
            for bar in bars:
                values.append((
                    bar.timestamp,
                    symbol,
                    float(bar.open),
                    float(bar.high),
                    float(bar.low),
                    float(bar.close),
                    int(bar.volume),
                    int(bar.trade_count) if bar.trade_count else None,
                    float(bar.vwap) if bar.vwap else None
                ))

        if values:
            execute_values(
                cursor,
                """
                INSERT INTO stock_candles_1d
                    (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol) DO NOTHING
                """,
                values
            )
            conn.commit()
            logger.info(f"[SUCCESS] Inserted {len(values):,} candles into stock_candles_1d")

        cursor.close()
        conn.close()

        progress['completed_windows'].append(window_key)
        progress['total_inserted'] += len(values)
        save_progress(progress)

        return len(values)

    except Exception as e:
        logger.error(f"[ERROR] Batch {batch_num} failed: {e}")
        progress['failed_batches'].append({
            'window': window_key,
            'error': str(e)
        })
        save_progress(progress)
        return 0


def _load_symbols_with_prices() -> list[tuple[str, float]]:
    """
    Load (symbol, price) pairs from stocks_in_price_range.json.
    Falls back to .txt file with price=0.0 if JSON not found.
    """
    script_dir = os.path.dirname(__file__)
    json_path = os.path.abspath(os.path.join(script_dir, '../../services/stocks_in_price_range.json'))

    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            data = json.load(f)
        stocks = data.get('stocks', [])
        return [(s['symbol'], float(s['price'])) for s in stocks if 'symbol' in s and 'price' in s]

    # Fallback: use .txt symbols with price=0.0
    symbols_path = _find_symbols_file()
    if symbols_path:
        symbols = load_symbols_from_file(symbols_path)
        logger.warning("JSON price file not found — seeding with price=0.0")
        return [(sym, 0.0) for sym in symbols]

    return []


def seed_tradable_stocks_by_date(symbols_with_prices: list[tuple[str, float]], trading_days: list[date_type]):
    """
    Populate tradable_stocks_by_date for all trading days in the backfill range.

    Required because backfill_1min_bars_trading() and backfill_hour_bars() query
    this table per day to get the symbol list. If it's empty, they silently skip
    every day and collect nothing.

    NOTE: This seeds every day with the SAME current symbol list. For historically
    accurate per-day lists, run historical_tradable_stocks.py first — that script
    populates this table correctly by fetching actual historical prices per day.

    Uses ON CONFLICT DO NOTHING — safe to re-run.
    """
    values = []
    for current_date in trading_days:
        for symbol, price in symbols_with_prices:
            values.append((current_date, symbol, price))

    if not values:
        logger.warning("No trading days found in range — skipping seed")
        return

    num_symbols = len(symbols_with_prices)
    num_days = len(trading_days)
    logger.info(f"Seeding tradable_stocks_by_date: {num_symbols:,} symbols × "
                f"{num_days} trading days = {len(values):,} rows")

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()
    try:
        execute_values(
            cursor,
            """
            INSERT INTO tradable_stocks_by_date (date, symbol, price)
            VALUES %s
            ON CONFLICT (date, symbol) DO NOTHING
            """,
            values,
            page_size=10_000,
        )
        conn.commit()
        logger.info(f"[OK] tradable_stocks_by_date seeded successfully")
    except Exception as e:
        logger.error(f"[ERROR] Failed to seed tradable_stocks_by_date: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def _find_symbols_file() -> str | None:
    """
    Look for the symbols file in two locations (in priority order):
      1. production/services/stocks_in_price_range.txt  (output of fetch_stocks_in_price_range.py)
      2. database/stocks_1_to_20.txt                    (canonical list used by run_trading.py)
    Returns the path if found, else None.
    """
    script_dir = os.path.dirname(__file__)  # production/data/backfill/

    candidates = [
        os.path.abspath(os.path.join(script_dir, '../../services/stocks_in_price_range.txt')),
        os.path.abspath(os.path.join(script_dir, '../../../database/stocks_1_to_20.txt')),
    ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def main():
    """Main optimized backfill: minute bars (8am-12pm), hour bars, and daily bars."""

    parser = argparse.ArgumentParser(
        description='Backfill historical OHLCV bars from Alpaca.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Backfill all of 2023 and 2024:
  python production/data/backfill/backfill_optimized.py --start 2023-01-01 --end 2024-12-31

  # Backfill last 90 calendar days from today:
  python production/data/backfill/backfill_optimized.py --days 90

  # Interactive mode (prompts for range and bar type):
  python production/data/backfill/backfill_optimized.py

Prerequisite for minute/hour bars:
  tradable_stocks_by_date must be populated first:
  python research/database_analysis/historical_tradable_stocks.py --start 2023-01-01 --end 2024-12-31
        """
    )
    parser.add_argument('--start', type=str, metavar='YYYY-MM-DD',
                        help='Start date for backfill (inclusive)')
    parser.add_argument('--end', type=str, metavar='YYYY-MM-DD',
                        help='End date for backfill (inclusive, defaults to today)')
    parser.add_argument('--days', type=int, metavar='N',
                        help='Backfill last N calendar days from today (overrides --start/--end)')
    parser.add_argument('--type', choices=['1min', 'hour', 'daily', 'all'],
                        help='Bar type to backfill (skips interactive prompt)')
    parser.add_argument('--status', action='store_true',
                        help='Show current backfill progress and exit (no backfill runs)')
    parser.add_argument('--reset', action='store_true',
                        help='Reset progress file and start fresh')
    parser.add_argument('--skip-seed', action='store_true',
                        help='Skip seeding tradable_stocks_by_date (use when already populated '
                             'by historical_tradable_stocks.py — avoids re-polluting accurate data)')
    args = parser.parse_args()

    # ── Status-only mode ───────────────────────────────────────────────────────
    if args.status:
        start = args.start or None
        end   = args.end   or None
        print_status(start_date=start, end_date=end)
        return

    logger.info("=" * 70)
    logger.info("  OPTIMIZED HISTORICAL DATA BACKFILL")
    logger.info("  (1-min trading window + hour bars + daily bars)")
    logger.info("=" * 70)

    # ── Load symbols ───────────────────────────────────────────────────────────
    symbols_path = _find_symbols_file()
    if not symbols_path:
        print("\n[ERROR] No symbols file found. Run this first:")
        print("  python production/services/fetch_stocks_in_price_range.py")
        return

    symbols = load_symbols_from_file(symbols_path)
    if not symbols:
        print(f"\n[ERROR] Symbols file is empty: {symbols_path}")
        return

    logger.info(f"Loaded {len(symbols):,} symbols from {os.path.basename(symbols_path)}")

    symbols_with_prices = _load_symbols_with_prices()
    logger.info(f"Loaded prices for {len(symbols_with_prices):,} symbols (for DB seed)")

    # ── Resolve date range ─────────────────────────────────────────────────────
    today = datetime.now(ET).date()

    if args.days:
        end_date   = today
        start_date = today - timedelta(days=args.days)
    elif args.start:
        start_date = datetime.strptime(args.start, '%Y-%m-%d').date()
        end_date   = datetime.strptime(args.end, '%Y-%m-%d').date() if args.end else today
    else:
        # Interactive
        print("\nHow much historical data do you want to backfill?")
        print("  1. 2 weeks  (14 days)  — fast test")
        print("  2. 1 month  (30 days)")
        print("  3. 3 months (90 days)")
        print("  4. 1 year   (365 days)")
        print("  5. Custom date range")
        days_choice = input("\nEnter choice (1-5): ").strip()

        if days_choice == "1":
            start_date, end_date = today - timedelta(days=14), today
        elif days_choice == "2":
            start_date, end_date = today - timedelta(days=30), today
        elif days_choice == "3":
            start_date, end_date = today - timedelta(days=90), today
        elif days_choice == "4":
            start_date, end_date = today - timedelta(days=365), today
        else:
            start_str = input("Start date (YYYY-MM-DD): ").strip()
            end_str   = input("End date   (YYYY-MM-DD, or Enter for today): ").strip()
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date   = datetime.strptime(end_str, '%Y-%m-%d').date() if end_str else today

    trading_days = get_trading_days(start_date, end_date)
    logger.info(f"Date range: {start_date} -> {end_date}  ({len(trading_days)} trading days)")

    # ── What to backfill ───────────────────────────────────────────────────────
    if args.type:
        backfill_choice = {'1min': '1', 'hour': '2', 'daily': '3', 'all': '4'}[args.type]
    else:
        print("\nSelect what to backfill:")
        print("  1. Minute bars only (8am-12pm -> stock_candles_1m)")
        print("  2. Hour bars only   (4am-8am  -> stock_candles_1h)")
        print("  3. Daily bars only             (stock_candles_1d)")
        print("  4. All three (recommended)")
        backfill_choice = input("\nEnter choice (1/2/3/4): ").strip()

    # ── Check for existing progress ────────────────────────────────────────────
    progress = load_progress()
    if args.reset:
        reset_progress()
        progress = load_progress()
    elif progress['completed_windows']:
        # Only prompt interactively when no CLI args provided (non-interactive runs skip this)
        if not (args.start or args.days or args.type):
            print(f"\nFound existing progress: {len(progress['completed_windows'])} windows completed")
            reset = input("Reset and start fresh? (y/n): ").strip().lower()
            if reset == 'y':
                reset_progress()
                progress = load_progress()

    if not (args.start or args.days or args.type):
        proceed = input("\nProceed with backfill? (y/n): ").strip().lower()
        if proceed != 'y':
            logger.info("Backfill cancelled")
            return

    # ── Seed tradable_stocks_by_date (required for minute + hour functions) ────
    if backfill_choice in ['1', '2', '4']:
        if args.skip_seed:
            logger.info("\n[SKIP] tradable_stocks_by_date seed skipped (--skip-seed flag set)")
            logger.info("       Assuming historical_tradable_stocks.py has already populated it correctly.")
        else:
            logger.info("\nSeeding tradable_stocks_by_date (skips existing rows)...")
            logger.warning("NOTE: If you already ran historical_tradable_stocks.py for this date range,")
            logger.warning("      use --skip-seed to avoid re-polluting with the static symbol list.")
            try:
                seed_tradable_stocks_by_date(symbols_with_prices, trading_days)
            except Exception as e:
                logger.error(f"Failed to seed tradable_stocks_by_date: {e}")
                logger.error("Cannot proceed with minute/hour backfill without this table.")
                return

    # ── Run backfill ───────────────────────────────────────────────────────────
    overall_start = time.time()
    total_inserted = 0
    batch_num = 1
    total_batches = 1

    logger.info(f"\n{'#'*70}")
    logger.info(f"BACKFILL STARTING")
    logger.info(f"{'#'*70}")

    if backfill_choice in ['1', '4']:
        inserted = backfill_1min_bars_trading(trading_days, batch_num, total_batches, progress)
        total_inserted += inserted
        time.sleep(2)

    if backfill_choice in ['2', '4']:
        inserted = backfill_hour_bars(trading_days, batch_num, total_batches, progress)
        total_inserted += inserted
        time.sleep(2)

    if backfill_choice in ['3', '4']:
        inserted = backfill_daily_bars(symbols, trading_days, batch_num, total_batches, progress)
        total_inserted += inserted

    # ── Summary ────────────────────────────────────────────────────────────────
    total_time = time.time() - overall_start
    logger.info("\n" + "=" * 70)
    logger.info("  BACKFILL COMPLETE!")
    logger.info("=" * 70)
    logger.info(f"Total candles inserted: {total_inserted:,}")
    logger.info(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)")
    logger.info(f"\nNext steps:")
    logger.info(f"  1. Start live collector: python production/data/collector/collect_data.py")
    logger.info(f"  2. Run trading:          python production/run_trading.py\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n[STOPPED] Backfill paused by user")
        logger.info("Progress saved! Run again to resume.")
    except Exception as e:
        logger.error(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
