#!/usr/bin/env python3
"""
Real-time Stock Data Collector
Continuously collects 1-minute candles from Alpaca and stores in TimescaleDB.
Run this during market hours to build your own historical database.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2
from psycopg2.extras import execute_values
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from datetime import datetime, timedelta
from config import Config
from dotenv import load_dotenv
import time
import pytz
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv()

# Database connection
DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

# Symbols to track (start with your debug stocks, expand later)
TRACKED_SYMBOLS = Config.DEBUG_STOCKS[:50]  # Start with 50 stocks

def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(DB_CONN)

def get_active_stocks():
    """Fetch all active tradable stocks from Alpaca"""
    logger.info("Fetching active stocks from Alpaca...")

    client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=Config.ALPACA_PAPER_TRADING
    )

    assets = client.get_all_assets()
    active_stocks = [
        a for a in assets
        if a.tradable and a.status == 'active' and a.exchange in ['NASDAQ', 'NYSE', 'ARCA']
    ]

    logger.info(f"Found {len(active_stocks):,} active stocks")
    return [a.symbol for a in active_stocks]

def update_stock_metadata():
    """Update stock metadata table with latest symbols"""
    logger.info("Updating stock metadata...")

    client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=Config.ALPACA_PAPER_TRADING
    )

    assets = client.get_all_assets()
    active_stocks = [a for a in assets if a.tradable and a.status == 'active']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Prepare batch insert
    values = []
    for asset in active_stocks:
        values.append((
            asset.symbol,
            asset.name,
            asset.exchange,
            asset.asset_class,
            asset.status,
            asset.tradable,
            asset.marginable,
            asset.shortable,
            asset.easy_to_borrow,
            asset.fractionable
        ))

    # Batch upsert
    execute_values(
        cursor,
        """
        INSERT INTO stock_metadata
            (symbol, name, exchange, asset_class, status, tradable, marginable,
             shortable, easy_to_borrow, fractionable, updated_at)
        VALUES %s
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name,
            exchange = EXCLUDED.exchange,
            status = EXCLUDED.status,
            tradable = EXCLUDED.tradable,
            updated_at = NOW()
        """,
        values
    )

    conn.commit()
    cursor.close()
    conn.close()

    logger.info(f"Updated metadata for {len(values):,} stocks")

def collect_minute_candles(symbols, lookback_minutes=5):
    """Collect latest minute candles for given symbols"""

    if not symbols:
        logger.warning("No symbols to collect")
        return 0

    logger.info(f"Collecting {lookback_minutes}min candles for {len(symbols)} symbols...")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    end = datetime.now(pytz.utc)
    start = end - timedelta(minutes=lookback_minutes)

    # Request bars
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Minute,
        start=start,
        end=end
    )

    try:
        bars_response = client.get_stock_bars(request)
    except Exception as e:
        logger.error(f"Error fetching bars: {e}")
        return 0

    # Insert into database
    conn = get_db_connection()
    cursor = conn.cursor()

    total_bars = 0
    values = []

    for symbol, bars in bars_response.data.items():
        for bar in bars:
            values.append((
                bar.timestamp,
                symbol,
                '1m',  # timeframe
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                int(bar.volume),
                int(bar.trade_count) if bar.trade_count else None,
                float(bar.vwap) if bar.vwap else None
            ))
            total_bars += 1

    if values:
        # Batch upsert (avoid duplicates)
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

    cursor.close()
    conn.close()

    logger.info(f"Inserted {total_bars} candles ({len(bars_response.data)} symbols)")
    return total_bars

def main_collection_loop():
    """Main loop - runs continuously during market hours"""

    logger.info("=" * 70)
    logger.info("  Stock Data Collector - Starting")
    logger.info("=" * 70)
    logger.info(f"Tracking {len(TRACKED_SYMBOLS)} symbols")
    logger.info(f"Database: {DB_CONN.split('@')[1]}")

    # Update metadata once at startup
    try:
        update_stock_metadata()
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")

    # Main collection loop
    iteration = 0
    while True:
        iteration += 1
        et = pytz.timezone('US/Eastern')
        now_et = datetime.now(et)
        hour = now_et.hour

        # Only collect during market hours (4am-8pm ET)
        if 4 <= hour <= 20:
            logger.info(f"\n[Iteration {iteration}] {now_et.strftime('%Y-%m-%d %H:%M %Z')}")

            try:
                # Collect last 5 minutes of data (catches up if we missed any)
                bars_collected = collect_minute_candles(TRACKED_SYMBOLS, lookback_minutes=5)

                if bars_collected > 0:
                    logger.info(f"[OK] Collected {bars_collected} bars")
                else:
                    logger.warning("[WARNING] No bars collected (market closed?)")

            except Exception as e:
                logger.error(f"[ERROR] Collection failed: {e}")
                import traceback
                traceback.print_exc()

            # Wait 60 seconds before next collection
            logger.info("Waiting 60s until next collection...")
            time.sleep(60)

        else:
            logger.info(f"Outside market hours ({hour}:00 ET). Sleeping 5 minutes...")
            time.sleep(300)  # Sleep 5 minutes

if __name__ == "__main__":
    try:
        main_collection_loop()
    except KeyboardInterrupt:
        logger.info("\n\n[STOPPED] Data collection stopped by user")
    except Exception as e:
        logger.error(f"\n\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
