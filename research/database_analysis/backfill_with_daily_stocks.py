#!/usr/bin/env python3
"""
Backfill Historical Candle Data Using Daily-Accurate Stock Lists

This script backfills minute (8am-12pm) and hourly (4am-8am) data using the
per-day tradable stock lists created by historical_tradable_stocks.py

Phase 1 MUST complete first: python historical_tradable_stocks.py --start 2025-01-01 --end 2025-11-30

Usage:
  # Backfill minute data for Jan 2025 - Nov 2025
  python backfill_with_daily_stocks.py --type minute --start 2025-01-01 --end 2025-11-30

  # Backfill hourly data for Jan 2025 - Feb 2026
  python backfill_with_daily_stocks.py --type hourly --start 2025-01-01 --end 2026-02-28

  # Backfill both
  python backfill_with_daily_stocks.py --type both --start 2025-01-01 --end 2026-02-28
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

import logging
from datetime import datetime, timedelta
import argparse
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from config import Config
from utils.query_helpers import StockDataDB
from utils.trading_calendar import get_trading_days as get_nyse_trading_days
import time

# Trading hours timezone
ET = pytz.timezone('America/New_York')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_trading_days(start_date, end_date):
    """
    Get list of trading days using NYSE official calendar.
    Excludes weekends and US market holidays (New Year's Day, Thanksgiving, Christmas, etc.)
    """
    return get_nyse_trading_days(start_date, end_date)


def get_stocks_for_date(date):
    """Get tradable stocks for a specific date from database"""
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT symbol FROM tradable_stocks_by_date
            WHERE date = %s
            ORDER BY symbol
        """, (date,))
        return [row[0] for row in cursor.fetchall()]


def backfill_minute_data(date, symbols, chunk_size=50):
    """
    Backfill minute bars (8am-12pm ET) for a specific date

    Args:
        date: datetime.date object
        symbols: list of stock symbols to fetch
        chunk_size: symbols per API request (Alpaca limit is typically 100)
    """
    if not symbols:
        logger.warning(f"  {date.strftime('%Y-%m-%d')}: No symbols to backfill")
        return 0

    # 8am-12pm ET with proper timezone awareness
    start_time = ET.localize(datetime.combine(date, datetime.min.time()).replace(hour=8, minute=0))
    end_time = ET.localize(datetime.combine(date, datetime.min.time()).replace(hour=12, minute=0))

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    total_candles = 0

    # Process in chunks
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbols) - 1) // chunk_size + 1

        try:
            logger.info(f"  {date.strftime('%Y-%m-%d')} Chunk {chunk_num}/{total_chunks}: fetching {len(chunk)} stocks")

            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                start=start_time,
                end=end_time
            )

            bars = client.get_stock_bars(request)

            # Insert into database
            candle_count = store_candles(bars, '1m', date)
            total_candles += candle_count
            logger.info(f"    Stored {candle_count} minute candles")

            # Respect rate limits (200 req/min)
            time.sleep(0.3)

        except Exception as e:
            logger.error(f"  Chunk {chunk_num}/{total_chunks} failed: {e}")
            continue

    return total_candles


def backfill_hourly_data(date, symbols, chunk_size=50):
    """
    Backfill hourly bars (4am-8am ET) for a specific date

    Args:
        date: datetime.date object
        symbols: list of stock symbols to fetch
        chunk_size: symbols per API request
    """
    if not symbols:
        logger.warning(f"  {date.strftime('%Y-%m-%d')}: No symbols to backfill")
        return 0

    # 4am-8am ET with proper timezone awareness
    start_time = ET.localize(datetime.combine(date, datetime.min.time()).replace(hour=4, minute=0))
    end_time = ET.localize(datetime.combine(date, datetime.min.time()).replace(hour=8, minute=0))

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    total_candles = 0

    # Process in chunks
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbols) - 1) // chunk_size + 1

        try:
            logger.info(f"  {date.strftime('%Y-%m-%d')} Chunk {chunk_num}/{total_chunks}: fetching {len(chunk)} stocks")

            request = StockBarsRequest(
                symbol_or_symbols=chunk,
                timeframe=TimeFrame(1, TimeFrameUnit.Hour),
                start=start_time,
                end=end_time
            )

            bars = client.get_stock_bars(request)

            # Insert into database
            candle_count = store_candles(bars, '1h', date)
            total_candles += candle_count
            logger.info(f"    Stored {candle_count} hourly candles")

            # Respect rate limits
            time.sleep(0.3)

        except Exception as e:
            logger.error(f"  Chunk {chunk_num}/{total_chunks} failed: {e}")
            continue

    return total_candles


def store_candles(bars_response, timeframe, date):
    """
    Insert candles into appropriate table (stock_candles_1m or stock_candles_1h)

    Args:
        bars_response: BarSet response from Alpaca API (has .data property)
        timeframe: '1m' or '1h'
        date: for logging

    Returns:
        count of candles stored
    """
    table_name = 'stock_candles_1m' if timeframe == '1m' else 'stock_candles_1h'
    count = 0

    with StockDataDB() as db:
        cursor = db.conn.cursor()

        # Iterate over BarSet.data which is a dict of {symbol: list_of_bar_objects}
        for symbol, bars in bars_response.data.items():
            for bar in bars:
                cursor.execute(f"""
                    INSERT INTO {table_name}
                    (time, symbol, open, high, low, close, volume, vwap)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (time, symbol) DO UPDATE SET
                    volume = EXCLUDED.volume,
                    close = EXCLUDED.close,
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    vwap = EXCLUDED.vwap
                """, (
                    bar.timestamp,
                    symbol,
                    float(bar.open),
                    float(bar.high),
                    float(bar.low),
                    float(bar.close),
                    int(bar.volume),
                    float(bar.vwap) if bar.vwap else None
                ))
                count += 1

        db.conn.commit()

    return count


def main():
    parser = argparse.ArgumentParser(description='Backfill historical candle data')
    parser.add_argument('--type', choices=['minute', 'hourly', 'both'], default='both',
                        help='Data type to backfill')
    parser.add_argument('--start', type=str, default='2025-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2026-02-28', help='End date (YYYY-MM-DD)')
    parser.add_argument('--skip-existing', action='store_true', help='Skip days with existing data')

    args = parser.parse_args()

    print("\n" + "="*80)
    print("  BACKFILL HISTORICAL CANDLE DATA")
    print("="*80)
    print(f"Type: {args.type}")
    print(f"Date range: {args.start} to {args.end}")
    print("="*80 + "\n")

    # Check that historical_tradable_stocks table exists
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'tradable_stocks_by_date'
        """)
        if not cursor.fetchone():
            logger.error("ERROR: tradable_stocks_by_date table not found!")
            logger.error("Please run historical_tradable_stocks.py first")
            return

    start = datetime.strptime(args.start, '%Y-%m-%d').date()
    end = datetime.strptime(args.end, '%Y-%m-%d').date()
    trading_days = get_trading_days(start, end)

    logger.info(f"Found {len(trading_days)} trading days to process\n")

    minute_total = 0
    hourly_total = 0

    for idx, date in enumerate(trading_days, 1):
        logger.info(f"[{idx}/{len(trading_days)}] {date.strftime('%Y-%m-%d %A')}")

        # Get stocks for this date
        stocks = get_stocks_for_date(date)
        if not stocks:
            logger.warning(f"  No stocks found in tradable_stocks_by_date for {date}")
            continue

        # Backfill minute data
        if args.type in ['minute', 'both']:
            minute_count = backfill_minute_data(date, stocks)
            minute_total += minute_count

        # Backfill hourly data
        if args.type in ['hourly', 'both']:
            hourly_count = backfill_hourly_data(date, stocks)
            hourly_total += hourly_count

    # Summary
    print("\n" + "="*80)
    print("  BACKFILL COMPLETE")
    print("="*80)
    if args.type in ['minute', 'both']:
        print(f"Minute candles: {minute_total:,}")
    if args.type in ['hourly', 'both']:
        print(f"Hourly candles: {hourly_total:,}")
    print("="*80 + "\n")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Cancelled by user")
    except Exception as e:
        logger.error(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
