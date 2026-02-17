#!/usr/bin/env python3
"""
Batched Historical Data Backfill with Progress Tracking
Safely backfills data in batches to handle failures gracefully.
Can be stopped and resumed without losing progress.
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

# Progress tracking file
PROGRESS_FILE = os.path.join(os.path.dirname(__file__), 'backfill_progress.json')

def load_progress():
    """Load progress from file"""
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {
        'completed_batches': [],
        'failed_batches': [],
        'last_batch': -1,
        'total_inserted': 0
    }

def save_progress(progress):
    """Save progress to file"""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)

def reset_progress():
    """Clear progress file"""
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        logger.info("Progress file cleared")

def backfill_batch(symbols, batch_num, total_batches, timeframe_name, days_back, progress):
    """Backfill a single batch of symbols"""

    logger.info(f"\n{'='*70}")
    logger.info(f"BATCH {batch_num}/{total_batches}: {len(symbols)} symbols")
    logger.info(f"{'='*70}")

    # Skip if already completed
    batch_key = f"{timeframe_name}_batch_{batch_num}"
    if batch_key in progress['completed_batches']:
        logger.info(f"Batch already completed, skipping...")
        return 0

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=days_back)

    # Determine timeframe
    if timeframe_name == 'minute':
        timeframe = TimeFrame.Minute
        tf_code = '1m'
    elif timeframe_name == 'hour':
        timeframe = TimeFrame.Hour
        tf_code = '1h'
    else:  # daily
        timeframe = TimeFrame.Day
        tf_code = '1d'

    try:
        # Fetch data
        logger.info(f"Fetching {timeframe_name} bars for {len(symbols)} symbols...")
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
            timeframe=timeframe,
            start=start,
            end=end
        )

        bars_response = client.get_stock_bars(request)

        # Insert into database
        conn = psycopg2.connect(DB_CONN)
        cursor = conn.cursor()

        values = []
        for symbol, bars in bars_response.data.items():
            for bar in bars:
                values.append((
                    bar.timestamp,
                    symbol,
                    tf_code,
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
                INSERT INTO stock_candles
                    (time, symbol, timeframe, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol, timeframe) DO NOTHING
                """,
                values
            )

            conn.commit()
            logger.info(f"[SUCCESS] Inserted {len(values):,} candles")
        else:
            logger.warning(f"[WARNING] No data returned for batch")

        cursor.close()
        conn.close()

        # Mark batch as completed
        progress['completed_batches'].append(batch_key)
        progress['last_batch'] = batch_num
        progress['total_inserted'] += len(values)
        save_progress(progress)

        return len(values)

    except Exception as e:
        logger.error(f"[ERROR] Batch {batch_num} failed: {e}")
        progress['failed_batches'].append({
            'batch_num': batch_num,
            'symbols': symbols,
            'error': str(e)
        })
        save_progress(progress)
        return 0

def backfill_batched(symbols, timeframe_name, days_back, batch_size):
    """Backfill with batching and progress tracking"""

    logger.info(f"\n{'='*70}")
    logger.info(f"BACKFILL: {timeframe_name} candles")
    logger.info(f"{'='*70}")
    logger.info(f"Total symbols: {len(symbols):,}")
    logger.info(f"Batch size: {batch_size}")
    logger.info(f"Days back: {days_back}")

    total_batches = (len(symbols) + batch_size - 1) // batch_size
    logger.info(f"Total batches: {total_batches}")

    # Load progress
    progress = load_progress()

    total_inserted = 0
    start_time = time.time()

    for i in range(0, len(symbols), batch_size):
        batch_num = i // batch_size + 1
        batch = symbols[i:i + batch_size]

        inserted = backfill_batch(
            batch,
            batch_num,
            total_batches,
            timeframe_name,
            days_back,
            progress
        )
        total_inserted += inserted

        # Small delay between batches
        if timeframe_name == 'minute':
            time.sleep(2)  # Longer delay for minute data
        else:
            time.sleep(1)

        # Show progress
        elapsed = time.time() - start_time
        eta = (elapsed / batch_num) * (total_batches - batch_num) if batch_num > 0 else 0
        logger.info(f"Progress: {batch_num}/{total_batches} batches | "
                   f"{total_inserted:,} candles | "
                   f"Elapsed: {elapsed/60:.1f}min | "
                   f"ETA: {eta/60:.1f}min")

    logger.info(f"\n[COMPLETE] {timeframe_name.upper()} backfill done!")
    logger.info(f"Total inserted: {total_inserted:,} candles")
    logger.info(f"Time taken: {(time.time() - start_time)/60:.1f} minutes")

    return total_inserted

def load_symbols_from_file(filepath):
    """Load symbols from JSON or TXT file"""
    if filepath.endswith('.json'):
        with open(filepath, 'r') as f:
            data = json.load(f)
            return data.get('symbols_only', [])
    else:  # .txt
        with open(filepath, 'r') as f:
            return [line.strip() for line in f if line.strip()]

def main():
    """Main batched backfill"""

    logger.info("=" * 70)
    logger.info("  BATCHED HISTORICAL DATA BACKFILL")
    logger.info("=" * 70)

    # Ask for symbol source
    print("\nSelect symbol source:")
    print("  1. Use Config.DEBUG_STOCKS (100 stocks)")
    print("  2. Load from stocks_1_to_20.txt")
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

    # Ask for batch size
    print("\nSelect batch size:")
    print("  1. Small (50 stocks/batch) - Safest, can resume easily")
    print("  2. Medium (200 stocks/batch) - Balanced")
    print("  3. Large (500 stocks/batch) - Fastest but longer batches")
    batch_choice = input("\nEnter choice (1/2/3): ").strip()

    if batch_choice == "1":
        batch_size = 50
    elif batch_choice == "2":
        batch_size = 200
    else:
        batch_size = 500

    # Ask to reset progress
    if os.path.exists(PROGRESS_FILE):
        reset = input("\nProgress file found. Reset and start fresh? (y/n): ").strip().lower()
        if reset == 'y':
            reset_progress()

    # Select data type
    print("\nSelect data to backfill:")
    print("  1. Minute candles (14 days)")
    print("  2. Daily candles (60 days)")
    print("  3. Hour candles (14 days)")
    print("  4. All (in sequence)")
    data_choice = input("\nEnter choice (1/2/3/4): ").strip()

    if data_choice == "1":
        backfill_batched(symbols, 'minute', 14, batch_size=min(batch_size, 50))
    elif data_choice == "2":
        backfill_batched(symbols, 'daily', 60, batch_size)
    elif data_choice == "3":
        backfill_batched(symbols, 'hour', 14, batch_size)
    elif data_choice == "4":
        logger.info("\n" + "="*70)
        logger.info("RUNNING ALL BACKFILLS IN SEQUENCE")
        logger.info("="*70)
        backfill_batched(symbols, 'daily', 60, batch_size)
        reset_progress()  # Reset for next type
        backfill_batched(symbols, 'hour', 14, batch_size)
        reset_progress()  # Reset for next type
        backfill_batched(symbols, 'minute', 14, batch_size=min(batch_size, 50))
    else:
        logger.error("Invalid choice")
        return

    logger.info("\n" + "=" * 70)
    logger.info("  BACKFILL COMPLETE!")
    logger.info("=" * 70)
    logger.info("\nNext steps:")
    logger.info("  1. Run 'python database/test_queries.py' to verify data")
    logger.info("  2. Run 'python database/collect_data.py' for live updates")
    logger.info("  3. Update scanner to query database\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n[STOPPED] Backfill paused by user")
        logger.info("Progress saved! Run again to resume from last batch.")
    except Exception as e:
        logger.error(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
