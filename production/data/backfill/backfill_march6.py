#!/usr/bin/env python3
"""
Quick backfill for March 6, 2026 data.
Fetches 1-min and hour bars from Alpaca and writes to database.
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
import pytz
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('US/Eastern')

# Alpaca SDK credentials
from config import Config
os.environ['APCA_API_BASE_URL'] = Config.ALPACA_BASE_URL

client = StockHistoricalDataClient(
    api_key=Config.ALPACA_API_KEY,
    secret_key=Config.ALPACA_SECRET_KEY
)

# Database
DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:changeme123@localhost:5432/stockdata')

def load_symbols_from_file(filepath):
    """Load symbols from text file"""
    with open(filepath, 'r') as f:
        return [line.strip() for line in f if line.strip()]

def backfill_minute_bars(symbols, target_date_str):
    """Backfill 1-minute bars for target date (8am-12pm ET)"""

    logger.info(f"Backfilling minute bars for {len(symbols)} symbols on {target_date_str}...")

    # Parse date
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

    # Window: 8am-12pm ET
    start_time = ET.localize(datetime.combine(target_date, datetime.min.time().replace(hour=8, minute=0)))
    end_time = ET.localize(datetime.combine(target_date, datetime.min.time().replace(hour=12, minute=0)))

    # Request from Alpaca
    logger.info(f"  Requesting bars from {start_time.strftime('%Y-%m-%d %H:%M %Z')} to {end_time.strftime('%Y-%m-%d %H:%M %Z')}...")

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start_time,
        end=end_time,
    )

    try:
        bars_data = client.get_stock_bars(request)
        logger.info(f"  Received data for {len(bars_data.data)} symbols")

        # Convert to list of tuples for insert
        rows = []
        for symbol, bars in bars_data.data.items():
            for bar in bars:
                rows.append((
                    symbol,
                    bar.timestamp,
                    float(bar.open),
                    float(bar.high),
                    float(bar.low),
                    float(bar.close),
                    int(bar.volume),
                ))

        # Insert into database
        if rows:
            conn = psycopg2.connect(DB_CONN)
            cur = conn.cursor()

            execute_values(cur, """
                INSERT INTO stock_candles_1m (symbol, time, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, rows)

            conn.commit()
            logger.info(f"  Inserted {len(rows)} minute bars into database")

            cur.close()
            conn.close()
        else:
            logger.warning("  No minute bars received from Alpaca")

    except Exception as e:
        logger.error(f"  Error fetching minute bars: {e}")

def backfill_hour_bars(symbols, target_date_str):
    """Backfill hour bars for target date (4am-8pm ET)"""

    logger.info(f"Backfilling hour bars for {len(symbols)} symbols on {target_date_str}...")

    # Parse date
    target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()

    # Window: 4am-8pm ET
    start_time = ET.localize(datetime.combine(target_date, datetime.min.time().replace(hour=4, minute=0)))
    end_time = ET.localize(datetime.combine(target_date, datetime.min.time().replace(hour=20, minute=0)))

    # Request from Alpaca
    logger.info(f"  Requesting bars from {start_time.strftime('%Y-%m-%d %H:%M %Z')} to {end_time.strftime('%Y-%m-%d %H:%M %Z')}...")

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Hour,
        start=start_time,
        end=end_time,
    )

    try:
        bars_data = client.get_stock_bars(request)
        logger.info(f"  Received data for {len(bars_data.data)} symbols")

        # Convert to list of tuples for insert
        rows = []
        for symbol, bars in bars_data.data.items():
            for bar in bars:
                rows.append((
                    symbol,
                    bar.timestamp,
                    float(bar.open),
                    float(bar.high),
                    float(bar.low),
                    float(bar.close),
                    int(bar.volume),
                ))

        # Insert into database
        if rows:
            conn = psycopg2.connect(DB_CONN)
            cur = conn.cursor()

            execute_values(cur, """
                INSERT INTO stock_candles_1h (symbol, time, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT DO NOTHING
            """, rows)

            conn.commit()
            logger.info(f"  Inserted {len(rows)} hour bars into database")

            cur.close()
            conn.close()
        else:
            logger.warning("  No hour bars received from Alpaca")

    except Exception as e:
        logger.error(f"  Error fetching hour bars: {e}")

if __name__ == '__main__':
    import json

    target_date = '2026-03-06'

    # Load all symbols
    symbols = load_symbols_from_file('production/services/stocks_in_price_range.txt')
    logger.info(f"Loaded {len(symbols)} symbols")

    # Backfill both hour and minute bars
    backfill_hour_bars(symbols, target_date)
    backfill_minute_bars(symbols, target_date)

    logger.info("\nBackfill complete!")
