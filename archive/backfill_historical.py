#!/usr/bin/env python3
"""
Historical Data Backfill Script
One-time script to populate database with 30-60 days of historical data.
Use this to jumpstart your database for backtesting.
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
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

def backfill_daily_candles(symbols, days_back=60):
    """Backfill daily candles for given symbols"""

    logger.info(f"Backfilling {days_back} days of daily candles for {len(symbols)} symbols...")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=days_back + 5)  # Add buffer for weekends

    # Chunk symbols (API limits)
    chunk_size = 100
    total_inserted = 0

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1}/{(len(symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")

        try:
            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Day,
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
                        '1d',
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
                total_inserted += len(values)
                logger.info(f"  Inserted {len(values)} daily candles")

            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            continue

    logger.info(f"[COMPLETE] Backfilled {total_inserted} daily candles")
    return total_inserted

def backfill_hour_candles(symbols, days_back=14):
    """Backfill hour candles for premarket analysis"""

    logger.info(f"Backfilling {days_back} days of hour candles for {len(symbols)} symbols...")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=days_back)

    chunk_size = 50  # Smaller chunks for hour data
    total_inserted = 0

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1}/{(len(symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")

        try:
            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Hour,
                start=start,
                end=end
            )

            bars_response = client.get_stock_bars(request)

            conn = psycopg2.connect(DB_CONN)
            cursor = conn.cursor()

            values = []
            for symbol, bars in bars_response.data.items():
                for bar in bars:
                    values.append((
                        bar.timestamp,
                        symbol,
                        '1h',
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
                total_inserted += len(values)
                logger.info(f"  Inserted {len(values)} hour candles")

            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            continue

    logger.info(f"[COMPLETE] Backfilled {total_inserted} hour candles")
    return total_inserted

def backfill_minute_candles(symbols, days_back=14):
    """Backfill minute candles for Ross Cameron momentum analysis"""

    logger.info(f"Backfilling {days_back} days of MINUTE candles for {len(symbols)} symbols...")
    logger.warning(f"This will fetch ~{days_back * 870 * len(symbols):,} candles (may take 30-60 min)")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now()
    start = end - timedelta(days=days_back)

    # SMALLER chunks for minute data (more API calls but safer)
    chunk_size = 10  # Only 10 symbols at a time for minute data
    total_inserted = 0

    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        logger.info(f"Processing chunk {i//chunk_size + 1}/{(len(symbols)-1)//chunk_size + 1} ({len(chunk)} symbols)...")

        try:
            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame.Minute,
                start=start,
                end=end
            )

            bars_response = client.get_stock_bars(request)

            conn = psycopg2.connect(DB_CONN)
            cursor = conn.cursor()

            values = []
            for symbol, bars in bars_response.data.items():
                for bar in bars:
                    values.append((
                        bar.timestamp,
                        symbol,
                        '1m',
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
                total_inserted += len(values)
                logger.info(f"  Inserted {len(values):,} minute candles")

            cursor.close()
            conn.close()

            # Small delay to avoid rate limits
            import time
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error processing chunk: {e}")
            continue

    logger.info(f"[COMPLETE] Backfilled {total_inserted:,} minute candles")
    return total_inserted

def main():
    """Run backfill for all tracked stocks"""

    logger.info("=" * 70)
    logger.info("  Historical Data Backfill")
    logger.info("=" * 70)

    symbols = Config.DEBUG_STOCKS[:100]  # Start with 100 stocks
    logger.info(f"Symbols to backfill: {len(symbols)}")

    print("\nSelect backfill option:")
    print("  1. Minute candles (14 days) - For Ross Cameron strategy - ~30-60 min")
    print("  2. Daily candles (60 days) - For long-term backtesting - ~5-10 min")
    print("  3. Hour candles (14 days) - For premarket analysis - ~10-15 min")
    print("  4. All (minute + daily + hour) - RECOMMENDED - ~45-90 min")
    choice = input("\nEnter choice (1/2/3/4): ").strip()

    if choice == "1":
        backfill_minute_candles(symbols, days_back=14)
    elif choice == "2":
        backfill_daily_candles(symbols, days_back=60)
    elif choice == "3":
        backfill_hour_candles(symbols, days_back=14)
    elif choice == "4":
        logger.info("\nBackfilling ALL data types (this will take 45-90 minutes)...")
        backfill_daily_candles(symbols, days_back=60)
        backfill_hour_candles(symbols, days_back=14)
        backfill_minute_candles(symbols, days_back=14)
    else:
        logger.error("Invalid choice")
        return

    logger.info("\n" + "=" * 70)
    logger.info("  Backfill Complete!")
    logger.info("=" * 70)
    logger.info("Next steps:")
    logger.info("  1. Run 'python database/test_queries.py' to verify data")
    logger.info("  2. Run 'python database/collect_data.py' for live updates")
    logger.info("  3. Update scanner to query database instead of APIs\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Backfill cancelled by user")
    except Exception as e:
        logger.error(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
