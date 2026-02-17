#!/usr/bin/env python3
"""
Optimized Historical Data Backfill with Time-Window Filtering
Reduces data volume by 70% using strategic timeframe selection:
- Minute bars: 9am-12pm only (core trading window for Ross Cameron strategy)
- Hour bars: All day 4am-8pm (premarket + afternoon + after-hours)
- Daily bars: 60 days for volume calculations

For 4,000 stocks:
- Storage: ~1.5 GB (vs 4.9 GB full minute data)
- Time: ~8-10 hours (vs 33 hours)
- Can expand to full minute data later without conflicts
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
from config import Config
from dotenv import load_dotenv
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
MINUTE_WINDOW_START = 9  # 9am ET
MINUTE_WINDOW_END = 12   # 12pm ET (noon)

def load_progress():
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {
        'completed_windows': [],
        'failed_batches': [],
        'total_inserted': 0,
        'last_updated': None
    }

def save_progress(progress):
    """Save progress to file"""
    progress['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

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

def backfill_minute_bars_optimized(symbols, batch_num, total_batches, days_back, progress):
    """Backfill minute bars for 9am-12pm window only using per-day datetime filtering"""

    window_key = f"minute_9to12_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"MINUTE BARS (9am-12pm) - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")
    logger.info(f"Fetching {len(symbols)} symbols, {days_back} days (per-day API calls)")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    all_values = []
    total_api_calls = 0

    try:
        # Fetch each day separately with exact 9am-12pm time window
        for day_offset in range(days_back):
            current_date = datetime.now(ET).date() - timedelta(days=day_offset)

            # Create datetime for 9:00 AM ET that day
            start_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=9, minute=0)))

            # Create datetime for 12:00 PM ET that day
            end_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=12, minute=0)))

            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() >= 5:
                continue

            # Skip future dates
            if current_date > datetime.now(ET).date():
                continue

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=symbols,
                    timeframe=TimeFrame.Minute,
                    start=start_dt,
                    end=end_dt
                )

                bars_response = client.get_stock_bars(request)
                total_api_calls += 1

                # Collect values from this day
                for symbol, bars in bars_response.data.items():
                    for bar in bars:
                        all_values.append((
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

                # Small delay between API calls
                time.sleep(0.5)

                if (day_offset + 1) % 5 == 0:
                    logger.info(f"  Progress: {day_offset + 1}/{days_back} days, {total_api_calls} API calls, {len(all_values):,} bars collected")

            except Exception as day_error:
                logger.warning(f"  [WARN] Failed to fetch {current_date}: {day_error}")
                continue

        # Insert all collected values into 1m table
        if all_values:
            execute_values(
                cursor,
                """
                INSERT INTO stock_candles_1m
                    (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol) DO NOTHING
                """,
                all_values
            )

            conn.commit()
            logger.info(f"[SUCCESS] Made {total_api_calls} API calls (per-day filtering)")
            logger.info(f"          Inserted {len(all_values):,} candles into stock_candles_1m (ONLY 9am-12pm data fetched)")
        else:
            logger.warning(f"[WARNING] No data collected")

        cursor.close()
        conn.close()

        # Mark as completed
        progress['completed_windows'].append(window_key)
        progress['total_inserted'] += len(all_values)
        save_progress(progress)

        return len(all_values)

    except Exception as e:
        logger.error(f"[ERROR] Batch {batch_num} failed: {e}")
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        progress['failed_batches'].append({
            'window': window_key,
            'symbols': symbols,
            'error': str(e)
        })
        save_progress(progress)
        return 0

def backfill_hour_bars(symbols, batch_num, total_batches, days_back, progress):
    """Backfill hour bars for entire day (4am-8pm)"""

    window_key = f"hour_allday_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"HOUR BARS (All Day) - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=days_back)

    try:
        batch_start = time.time()

        logger.info(f"Fetching hour bars for {len(symbols)} symbols...")
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=TimeFrame.Hour,
            start=start,
            end=end
        )

        bars_response = client.get_stock_bars(request)
        fetch_time = time.time() - batch_start
        logger.info(f"API call completed in {fetch_time:.1f}s")

        # Insert all hour bars (no filtering needed)
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
                INSERT INTO stock_candles_1h
                    (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol) DO NOTHING
                """,
                values
            )

            conn.commit()
            logger.info(f"[SUCCESS] Inserted {len(values):,} candles into stock_candles_1h")

        cursor.close()
        conn.close()

        # Mark as completed
        progress['completed_windows'].append(window_key)
        progress['total_inserted'] += len(values)
        save_progress(progress)

        return len(values)

    except Exception as e:
        logger.error(f"[ERROR] Batch {batch_num} failed: {e}")
        progress['failed_batches'].append({
            'window': window_key,
            'symbols': symbols,
            'error': str(e)
        })
        save_progress(progress)
        return 0

def backfill_daily_bars(symbols, batch_num, total_batches, days_back, progress):
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

    end = datetime.now()
    start = end - timedelta(days=days_back + 5)

    try:
        batch_start = time.time()

        logger.info(f"Fetching daily bars for {len(symbols)} symbols...")
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
            'symbols': symbols,
            'error': str(e)
        })
        save_progress(progress)
        return 0

def main():
    """Main optimized backfill with time windows"""

    logger.info("=" * 70)
    logger.info("  OPTIMIZED HISTORICAL DATA BACKFILL")
    logger.info("  (Time-Window Filtered)")
    logger.info("=" * 70)

    # Get symbols
    print("\nSelect symbol source:")
    print("  1. Config.DEBUG_STOCKS (100 stocks - for testing)")
    print("  2. Load from stocks_1_to_20.txt (all stocks $1-$20)")
    print("  3. Custom file path")
    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == "1":
        symbols = Config.DEBUG_STOCKS
    elif choice == "2":
        filepath = os.path.join(os.path.dirname(__file__), 'stocks_1_to_20.txt')
        if not os.path.exists(filepath):
            logger.error(f"File not found: {filepath}")
            logger.info("Run: python database/fetch_stocks_1_to_20.py first")
            return
        symbols = load_symbols_from_file(filepath)
    else:
        filepath = input("Enter file path: ").strip()
        symbols = load_symbols_from_file(filepath)

    logger.info(f"\nLoaded {len(symbols):,} symbols")

    # Batch size
    print("\nSelect batch size:")
    print("  1. Small (50 stocks/batch) - Safest")
    print("  2. Medium (200 stocks/batch) - Recommended")
    print("  3. Large (500 stocks/batch) - Fastest")
    batch_choice = input("\nEnter choice (1/2/3): ").strip()

    if batch_choice == "1":
        batch_size = 50
    elif batch_choice == "2":
        batch_size = 200
    else:
        batch_size = 500

    # Check for existing progress
    progress = load_progress()
    if progress['completed_windows']:
        print(f"\nFound existing progress: {len(progress['completed_windows'])} windows completed")
        reset = input("Reset and start fresh? (y/n): ").strip().lower()
        if reset == 'y':
            reset_progress()
            progress = load_progress()

    # Calculate batches
    total_batches = (len(symbols) - 1) // batch_size + 1
    logger.info(f"\nWill process {total_batches} batches of up to {batch_size} stocks each")

    # Estimate data volume
    minute_candles = len(symbols) * 14 * 180  # 3 hours/day
    hour_candles = len(symbols) * 14 * 16    # 16 hours/day
    daily_candles = len(symbols) * 60

    total_candles = minute_candles + hour_candles + daily_candles
    storage_gb = (total_candles * 100) / 1024 / 1024 / 1024  # ~100 bytes per candle

    # Calculate API calls (more accurate time estimate)
    trading_days_14 = 10  # ~10 trading days in 14 calendar days
    minute_api_calls = total_batches * trading_days_14  # Per-day filtering
    other_api_calls = total_batches * 2  # Daily + Hour
    total_api_calls = minute_api_calls + other_api_calls
    estimated_minutes = (total_api_calls * 4) / 60  # ~4 seconds per API call

    print(f"\nData Volume Estimates:")
    print(f"  Minute bars (9am-12pm): {minute_candles:,} candles")
    print(f"  Hour bars (all day):    {hour_candles:,} candles")
    print(f"  Daily bars (60 days):   {daily_candles:,} candles")
    print(f"  Total:                  {total_candles:,} candles (~{storage_gb:.1f} GB)")
    print(f"\nAPI Call Estimates:")
    print(f"  Minute bars (per-day):  {minute_api_calls} calls ({total_batches} batches × {trading_days_14} days)")
    print(f"  Hour + Daily bars:      {other_api_calls} calls")
    print(f"  Total API calls:        {total_api_calls}")
    print(f"  Estimated time:         ~{estimated_minutes:.0f} minutes ({estimated_minutes/60:.1f} hours)")

    proceed = input("\nProceed with backfill? (y/n): ").strip().lower()
    if proceed != 'y':
        logger.info("Backfill cancelled")
        return

    # Run backfill
    overall_start = time.time()
    total_inserted = 0

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        batch_num = i // batch_size + 1

        logger.info(f"\n{'#'*70}")
        logger.info(f"BATCH {batch_num}/{total_batches} - {len(batch)} symbols")
        logger.info(f"{'#'*70}")

        # Daily bars (fastest, do first)
        inserted = backfill_daily_bars(batch, batch_num, total_batches, 60, progress)
        total_inserted += inserted
        time.sleep(1)

        # Hour bars
        inserted = backfill_hour_bars(batch, batch_num, total_batches, 14, progress)
        total_inserted += inserted
        time.sleep(1)

        # Minute bars (9am-12pm only)
        inserted = backfill_minute_bars_optimized(batch, batch_num, total_batches, 14, progress)
        total_inserted += inserted
        time.sleep(2)  # Longer delay for minute data

        # Progress summary
        elapsed = time.time() - overall_start
        eta = (elapsed / batch_num) * (total_batches - batch_num) if batch_num > 0 else 0
        logger.info(f"\n[PROGRESS] Batch {batch_num}/{total_batches} complete")
        logger.info(f"           Total inserted: {total_inserted:,} candles")
        logger.info(f"           Elapsed: {elapsed/60:.1f}min | ETA: {eta/60:.1f}min")

    # Complete
    total_time = time.time() - overall_start
    logger.info("\n" + "=" * 70)
    logger.info("  BACKFILL COMPLETE!")
    logger.info("=" * 70)
    logger.info(f"Total candles inserted: {total_inserted:,}")
    logger.info(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)")
    logger.info(f"\nNext steps:")
    logger.info(f"  1. Run 'python database/test_queries.py' to verify data")
    logger.info(f"  2. Run 'python database/collect_data.py' for live updates")
    logger.info(f"  3. Can expand to full minute data later with backfill_historical.py\n")

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
