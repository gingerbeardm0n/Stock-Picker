#!/usr/bin/env python3
"""
Optimized Historical Data Backfill with Hybrid Time-Window Filtering
Collects the data needed for accurate Ross Cameron relative volume calculation:
- 5-minute bars: 4am-8am (premarket session, low noise)
- 1-minute bars: 8am-12pm (full trading morning, precise signals)
- Hour bars: All day 4am-8pm (premarket + afternoon + after-hours)
- Daily bars: 60 days for volume calculations

For 4,000 stocks over 12 months (252 trading days):
- 5-min storage: ~25 GB (48 bars/day × 4000 × 252 days)
- 1-min storage: ~50 GB (240 bars/day × 4000 × 252 days)
- Hour storage: ~25 GB (16 bars/day × 4000 × 252 days)
- Daily storage: ~5 GB (252 bars × 4000 symbols)
- Total: ~105 GB (4am-12pm window only)
- Time: 5-10 days (parallel batching)
- ON CONFLICT DO NOTHING: safe to re-run, won't duplicate existing data
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from datetime import datetime, timedelta
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

# Premarket: 5-minute bars (lower noise, adequate for EMA seeding)
FIVEMIN_WINDOW_START = 4   # 4am ET
FIVEMIN_WINDOW_END   = 8   # 8am ET

# Trading morning: 1-minute bars (precise signals for entry/exit)
ONEMIN_WINDOW_START = 8    # 8am ET
ONEMIN_WINDOW_END   = 12   # 12pm ET (noon)

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

def backfill_5min_bars_premarket(symbols, batch_num, total_batches, days_back, progress):
    """Backfill 5-minute bars for 4am-8am premarket window using per-day datetime filtering"""

    window_key = f"5min_4to8_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed (5-min premarket)")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"5-MINUTE BARS (4am-8am Premarket) - Batch {batch_num}/{total_batches}")
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
        # Fetch each day separately with exact 4am-8am time window
        for day_offset in range(days_back):
            current_date = datetime.now(ET).date() - timedelta(days=day_offset)

            # Create datetime for 4:00 AM ET that day
            start_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=FIVEMIN_WINDOW_START, minute=0)))

            # Create datetime for 8:00 AM ET that day
            end_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=FIVEMIN_WINDOW_END, minute=0)))

            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() >= 5:
                continue

            # Skip future dates
            if current_date > datetime.now(ET).date():
                continue

            # GET DAILY-ACCURATE STOCKS FROM DATABASE
            try:
                with StockDataDB() as db:
                    db_cursor = db.conn.cursor()
                    db_cursor.execute("""
                        SELECT symbol FROM tradable_stocks_by_date
                        WHERE date = %s ORDER BY symbol
                    """, (current_date,))
                    symbols_for_day = [row[0] for row in db_cursor.fetchall()]
                    db_cursor.close()
            except Exception as db_error:
                logger.warning(f"  [WARN] Failed to fetch stocks for {current_date} from database: {db_error}")
                continue

            if not symbols_for_day:
                logger.debug(f"  [SKIP] No stocks in database for {current_date.strftime('%Y-%m-%d')}")
                continue

            try:
                # DEBUG: Log exactly what we're sending to the API
                if day_offset == 0:  # Only log first day to avoid spam
                    logger.info(f"  [DEBUG] Requesting 5-minute data:")
                    logger.info(f"    Start (EST): {start_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    Start (UTC): {start_dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    End (EST):   {end_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    End (UTC):   {end_dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}")

                request = StockBarsRequest(
                    symbol_or_symbols=symbols_for_day,
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

        # Insert all collected values into 1m table (same table, different time window)
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
            logger.info(f"          Inserted {len(all_values):,} candles into stock_candles_1m (4am-8am premarket)")
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
        logger.error(f"[ERROR] Batch {batch_num} (5-min premarket) failed: {e}")
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

def backfill_1min_bars_trading(symbols, batch_num, total_batches, days_back, progress):
    """Backfill 1-minute bars for 8am-12pm trading window using per-day datetime filtering"""

    window_key = f"1min_8to12_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed (1-min trading)")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"1-MINUTE BARS (8am-12pm Trading) - Batch {batch_num}/{total_batches}")
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
        # Fetch each day separately with exact 8am-12pm time window
        for day_offset in range(days_back):
            current_date = datetime.now(ET).date() - timedelta(days=day_offset)

            # Create datetime for 8:00 AM ET that day
            start_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=ONEMIN_WINDOW_START, minute=0)))

            # Create datetime for 12:00 PM ET that day
            end_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=ONEMIN_WINDOW_END, minute=0)))

            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() >= 5:
                continue

            # Skip future dates
            if current_date > datetime.now(ET).date():
                continue

            # GET DAILY-ACCURATE STOCKS FROM DATABASE
            try:
                with StockDataDB() as db:
                    db_cursor = db.conn.cursor()
                    db_cursor.execute("""
                        SELECT symbol FROM tradable_stocks_by_date
                        WHERE date = %s ORDER BY symbol
                    """, (current_date,))
                    symbols_for_day = [row[0] for row in db_cursor.fetchall()]
                    db_cursor.close()
            except Exception as db_error:
                logger.warning(f"  [WARN] Failed to fetch stocks for {current_date} from database: {db_error}")
                continue

            if not symbols_for_day:
                logger.debug(f"  [SKIP] No stocks in database for {current_date.strftime('%Y-%m-%d')}")
                continue

            try:
                # DEBUG: Log exactly what we're sending to the API
                if day_offset == 0:  # Only log first day to avoid spam
                    logger.info(f"  [DEBUG] Requesting 1-minute data:")
                    logger.info(f"    Start (EST): {start_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    Start (UTC): {start_dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    End (EST):   {end_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    logger.info(f"    End (UTC):   {end_dt.astimezone(pytz.utc).strftime('%Y-%m-%d %H:%M:%S %Z')}")

                request = StockBarsRequest(
                    symbol_or_symbols=symbols_for_day,
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
            logger.info(f"          Inserted {len(all_values):,} candles into stock_candles_1m (8am-12pm trading)")
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
        logger.error(f"[ERROR] Batch {batch_num} (1-min trading) failed: {e}")
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
    """Backfill hour bars (4am-8pm) using per-day datetime filtering and daily-accurate stock lists"""

    window_key = f"hour_allday_batch_{batch_num}"
    if window_key in progress['completed_windows']:
        logger.info(f"[SKIP] Batch {batch_num} already completed")
        return 0

    logger.info(f"\n{'='*70}")
    logger.info(f"HOUR BARS (4am-8pm All Day) - Batch {batch_num}/{total_batches}")
    logger.info(f"{'='*70}")
    logger.info(f"Fetching {days_back} days (per-day, 400 symbols per API call)")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    all_values = []
    total_api_calls = 0

    try:
        # Fetch each day separately with 4am-8pm time window
        for day_offset in range(days_back):
            current_date = datetime.now(ET).date() - timedelta(days=day_offset)

            # Create datetime for 4:00 AM ET that day
            start_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=4, minute=0)))

            # Create datetime for 8:00 PM ET that day (20:00 in 24-hour)
            end_dt = ET.localize(datetime.combine(current_date, datetime.min.time().replace(hour=20, minute=0)))

            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() >= 5:
                continue

            # Skip future dates
            if current_date > datetime.now(ET).date():
                continue

            # GET DAILY-ACCURATE STOCKS FROM DATABASE
            try:
                with StockDataDB() as db:
                    db_cursor = db.conn.cursor()
                    db_cursor.execute("""
                        SELECT symbol FROM tradable_stocks_by_date
                        WHERE date = %s ORDER BY symbol
                    """, (current_date,))
                    symbols_for_day = [row[0] for row in db_cursor.fetchall()]
                    db_cursor.close()
            except Exception as db_error:
                logger.warning(f"  [WARN] Failed to fetch stocks for {current_date} from database: {db_error}")
                continue

            if not symbols_for_day:
                logger.debug(f"  [SKIP] No stocks in database for {current_date.strftime('%Y-%m-%d')}")
                continue

            # Batch symbols in groups of 400 to avoid API limits
            symbol_batch_size = 400
            for batch_start in range(0, len(symbols_for_day), symbol_batch_size):
                batch_end = min(batch_start + symbol_batch_size, len(symbols_for_day))
                symbols_batch = symbols_for_day[batch_start:batch_end]

                try:
                    request = StockBarsRequest(
                        symbol_or_symbols=symbols_batch,
                        timeframe=TimeFrame.Hour,
                        start=start_dt,
                        end=end_dt
                    )

                    bars_response = client.get_stock_bars(request)
                    total_api_calls += 1

                    # Collect values from this day/batch
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

                except Exception as batch_error:
                    logger.warning(f"  [WARN] Failed to fetch batch {batch_start}-{batch_end} for {current_date}: {batch_error}")
                    continue

            if (day_offset + 1) % 5 == 0:
                logger.info(f"  Progress: {day_offset + 1}/{days_back} days, {total_api_calls} API calls, {len(all_values):,} bars collected")

        # Insert all collected values into hour table
        if all_values:
            execute_values(
                cursor,
                """
                INSERT INTO stock_candles_1h
                    (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol) DO NOTHING
                """,
                all_values
            )

            conn.commit()
            logger.info(f"[SUCCESS] Made {total_api_calls} API calls (per-day, 400 symbols per batch)")
            logger.info(f"          Inserted {len(all_values):,} candles into stock_candles_1h (4am-8pm)")
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
        logger.error(f"[ERROR] Batch {batch_num} (hour bars) failed: {e}")
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
    logger.info("  (Time-Window Filtered, Daily-Accurate Stock Lists)")
    logger.info("=" * 70)
    logger.info("\nNote: Symbols will be loaded from tradable_stocks_by_date table")
    logger.info("      (one query per day for historically accurate lists)\n")

    # Check for existing progress
    progress = load_progress()
    if progress['completed_windows']:
        print(f"\nFound existing progress: {len(progress['completed_windows'])} windows completed")
        reset = input("Reset and start fresh? (y/n): ").strip().lower()
        if reset == 'y':
            reset_progress()
            progress = load_progress()

    # Ask for data range
    print("\nHow much historical data do you want to backfill?")
    print("  1. 2 weeks (14 days) - Fast test")
    print("  2. 1 month (30 days)")
    print("  3. 6 weeks (45 days)")
    print("  4. 3 months (60 days)")
    print("  5. All of 2025 (416 days, ~252 trading days)")
    print("  6. Custom (enter days)")
    days_choice = input("\nEnter choice (1-6): ").strip()

    if days_choice == "1":
        days_back_minute = 14
        days_back_hour = 14
        days_back_daily = 14
    elif days_choice == "2":
        days_back_minute = 30
        days_back_hour = 30
        days_back_daily = 30
    elif days_choice == "3":
        days_back_minute = 45
        days_back_hour = 45
        days_back_daily = 45
    elif days_choice == "4":
        days_back_minute = 60
        days_back_hour = 60
        days_back_daily = 60
    elif days_choice == "5":
        # All of 2025: Jan 1 to Dec 31 = 365 calendar days
        # Feb 20, 2026 to Jan 1, 2025 = 416 calendar days
        days_back_minute = 416
        days_back_hour = 416
        days_back_daily = 416
    else:
        try:
            days_back_minute = int(input("Days back (will apply to 5-min, 1-min, hour, and daily bars): ").strip())
            days_back_hour = days_back_minute
            days_back_daily = days_back_minute
        except ValueError:
            logger.error("Invalid input, using default (14 days)")
            days_back_minute = 14
            days_back_hour = 14
            days_back_daily = 14

    logger.info(f"\nBackfill range: {days_back_minute} days (5-min premarket + 1-min trading), {days_back_hour} days (hour), {days_back_daily} days (daily)")

    # Estimate data volume (hourly + 1-min trading window only)
    trading_days_multiplier = max(days_back_minute, days_back_hour) // 2  # ~50% of calendar days are trading days
    avg_stocks_per_day = 3500  # Typical number of stocks in $1-$20 range

    # 1-minute bars: 8am-12pm = 4 hours = 240 bars/day per symbol
    onemin_candles = avg_stocks_per_day * trading_days_multiplier * 240

    # Hour bars: 4am-8am = 4 hours = 4 bars/day per symbol (premarket only)
    hour_candles = avg_stocks_per_day * trading_days_multiplier * 4

    total_candles = onemin_candles + hour_candles
    storage_gb = (total_candles * 100) / 1024 / 1024 / 1024  # ~100 bytes per candle

    # Calculate API calls (more accurate time estimate)
    trading_days_minute = max(1, days_back_minute // 2)  # ~50% trading days
    trading_days_hour = max(1, days_back_hour // 2)
    avg_stocks = 3994  # From tradable_stocks_by_date
    symbol_batch_size = 400

    # Hour bars: ~10 batches per trading day (3994 stocks / 400 per batch)
    hour_batches_per_day = max(1, (avg_stocks + symbol_batch_size - 1) // symbol_batch_size)
    onemin_api_calls = trading_days_minute   # One call per trading day (all symbols at once for minutes)
    hour_api_calls = trading_days_hour * hour_batches_per_day  # Multiple calls per day with batching
    total_api_calls = onemin_api_calls + hour_api_calls
    estimated_minutes = (total_api_calls * 10) / 60  # ~10 seconds per API call

    print(f"\nData Volume Estimates (Hourly + 1-minute):")
    print(f"  Average stocks per day:  ~{avg_stocks_per_day:,}")
    print(f"  1-min bars (8am-12pm):   {onemin_candles:,} candles")
    print(f"  Hour bars (4am-8am):     {hour_candles:,} candles")
    print(f"  Total:                   {total_candles:,} candles (~{storage_gb:.1f} GB)")
    print(f"\nAPI Call Estimates (Daily-Accurate Lists):")
    print(f"  1-min bars:              {onemin_api_calls} calls ({trading_days_minute} trading days)")
    print(f"  Hour bars:               {hour_api_calls} calls ({hour_batches_per_day} batches/day × {trading_days_hour} days, 400 symbols/batch)")
    print(f"  Total API calls:         {total_api_calls}")
    print(f"  Estimated time:          ~{estimated_minutes:.0f} minutes ({estimated_minutes/60:.1f} hours)")
    print(f"  NOTE: ON CONFLICT DO NOTHING — new/existing data will be handled safely")

    print("\nSelect what to backfill:")
    print("  1. Hour bars only (4am-8pm)")
    print("  2. Minute bars only (8am-12pm)")
    print("  3. Both (hour + minute)")
    backfill_choice = input("\nEnter choice (1/2/3): ").strip()

    proceed = input("\nProceed with backfill? (y/n): ").strip().lower()
    if proceed != 'y':
        logger.info("Backfill cancelled")
        return

    # Run backfill (no batching needed — daily queries happen inside each function)
    overall_start = time.time()
    total_inserted = 0
    dummy_batch = []  # Empty list since we query DB for stocks per day
    batch_num = 1
    total_batches = 1

    logger.info(f"\n{'#'*70}")
    logger.info(f"BACKFILL STARTING (Daily-Accurate Stock Lists)")
    logger.info(f"{'#'*70}")

    # Hour bars (4am-8pm premarket)
    if backfill_choice in ['1', '3']:
        inserted = backfill_hour_bars(dummy_batch, batch_num, total_batches, days_back_hour, progress)
        total_inserted += inserted
        time.sleep(2)

    # 1-minute bars (8am-12pm trading)
    if backfill_choice in ['2', '3']:
        inserted = backfill_1min_bars_trading(dummy_batch, batch_num, total_batches, days_back_minute, progress)
        total_inserted += inserted
        time.sleep(2)

    # Progress summary
    elapsed = time.time() - overall_start
    logger.info(f"\n[PROGRESS] Backfill complete")
    logger.info(f"           Total inserted: {total_inserted:,} candles")
    logger.info(f"           Elapsed: {elapsed/60:.1f}min")

    # Complete
    total_time = time.time() - overall_start
    logger.info("\n" + "=" * 70)
    logger.info("  BACKFILL COMPLETE!")
    logger.info("=" * 70)
    logger.info(f"Total candles inserted: {total_inserted:,}")
    logger.info(f"Total time: {total_time/60:.1f} minutes ({total_time/3600:.1f} hours)")
    logger.info(f"\nNext steps:")
    logger.info(f"  1. Verify data: check DB for 5-min (4am-8am) and 1-min (8am-12pm) bars")
    logger.info(f"  2. Start live collector: python data/collector/collect_data.py")
    logger.info(f"  3. Run simulator: python simulator/simulate_date_range.py --start 2025-01-01 --end 2025-12-31")
    logger.info(f"  4. Note: Full data collection will take 5-10 days with parallel batching\n")

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
