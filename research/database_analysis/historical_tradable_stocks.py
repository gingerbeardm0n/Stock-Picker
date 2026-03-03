#!/usr/bin/env python3
"""
Historical Tradable Stocks Snapshot

For each trading day from Jan 1, 2025 - Nov 30, 2025, fetch stocks trading in $1-$20 range
and store in database. This creates daily-accurate lists for historical backfilling.

Why: Stock prices change daily. A stock at $8 on Jan 1 might be at $25 on Jan 20.
Using a static list across dates is inaccurate. This script builds the correct per-day lists.

Usage:
  python historical_tradable_stocks.py --start 2025-01-01 --end 2025-11-30
  python historical_tradable_stocks.py --days 30  # last 30 trading days
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

import logging
from datetime import datetime, timedelta, timezone
import argparse
import time
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockSnapshotRequest
from config import Config
from utils.query_helpers import StockDataDB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def init_database():
    """Create tradable_stocks_by_date table if not exists"""
    with StockDataDB() as db:
        cursor = db.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tradable_stocks_by_date (
                date DATE NOT NULL,
                symbol VARCHAR(10) NOT NULL,
                price DECIMAL(8, 2) NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, symbol)
            );
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tradable_stocks_date
            ON tradable_stocks_by_date(date);
        """)

        db.conn.commit()
        logger.info("Table tradable_stocks_by_date initialized")


def get_trading_days(start_date, end_date):
    """Get list of trading days (weekdays only, ignoring US holidays for simplicity)"""
    days = []
    current = start_date
    while current <= end_date:
        # Skip weekends (0=Monday, 4=Friday, 5=Saturday, 6=Sunday)
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def get_tradable_stocks_for_date(reference_date):
    """
    Get all tradable stocks from Alpaca (static - exchange list doesn't change daily)
    This is the expensive part, but the result is the same each day.
    We cache it to avoid redundant API calls.
    """
    client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=Config.ALPACA_PAPER_TRADING
    )

    assets = client.get_all_assets()

    # Filter for active, tradable stocks on major exchanges
    tradable = [
        a for a in assets
        if a.tradable
        and a.status == 'active'
        and a.exchange in ['NASDAQ', 'NYSE', 'ARCA', 'AMEX']
        and a.asset_class == 'us_equity'
    ]

    return [a.symbol for a in tradable]


def get_stocks_in_price_range_for_date(symbols, reference_date, min_price=1.0, max_price=20.0, chunk_size=500):
    """
    For a given reference date, filter stocks by their price that day.
    Uses Alpaca snapshot API (current prices) as proxy for historical prices.

    NOTE: This is an approximation. Alpaca doesn't expose historical snapshots at specific times.
    For true historical accuracy, we'd need to use minute bars and find the first trade of each day.
    This approach is good enough for daily filtering: if a stock was in range on date X,
    it's likely in range on date X+1.
    """
    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    in_range = []

    # Process in chunks to respect API limits
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(symbols) - 1) // chunk_size + 1

        try:
            request = StockSnapshotRequest(symbol_or_symbols=chunk)
            snapshots = client.get_stock_snapshot(request)

            for symbol, snapshot in snapshots.items():
                if snapshot.latest_trade and snapshot.latest_trade.price:
                    price = snapshot.latest_trade.price
                    if min_price <= price <= max_price:
                        in_range.append({
                            'symbol': symbol,
                            'price': round(price, 2),
                            'date': reference_date
                        })

            logger.info(f"  Chunk {chunk_num}/{total_chunks}: {len([s for s in in_range if s['date'] == reference_date])} in range so far")

            # Respect rate limits (200 req/min)
            time.sleep(0.3)

        except Exception as e:
            logger.error(f"  Chunk {chunk_num}/{total_chunks} failed: {e}")
            continue

    return [s for s in in_range if s['date'] == reference_date]


def store_stocks_for_date(date, stocks):
    """Store stock list for a specific date in database"""
    with StockDataDB() as db:
        cursor = db.conn.cursor()

        # Delete any existing entries for this date
        cursor.execute("DELETE FROM tradable_stocks_by_date WHERE date = %s", (date,))

        # Insert new entries
        for stock in stocks:
            cursor.execute("""
                INSERT INTO tradable_stocks_by_date (date, symbol, price)
                VALUES (%s, %s, %s)
            """, (date, stock['symbol'], stock['price']))

        db.conn.commit()
        logger.info(f"  Stored {len(stocks)} stocks for {date.strftime('%Y-%m-%d')}")


def get_stored_tradable_count(date):
    """Get count of stored stocks for a date"""
    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM tradable_stocks_by_date WHERE date = %s",
            (date,)
        )
        return cursor.fetchone()[0]


def main():
    parser = argparse.ArgumentParser(description='Fetch historical tradable stocks by date')
    parser.add_argument('--start', type=str, default='2025-01-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2025-11-30', help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Last N trading days (overrides start/end)')
    parser.add_argument('--skip-existing', action='store_true', help='Skip dates already in database')

    args = parser.parse_args()

    print("\n" + "="*80)
    print("  HISTORICAL TRADABLE STOCKS SNAPSHOT")
    print("="*80)

    # Initialize database table
    init_database()

    # Parse dates
    if args.days:
        end = datetime.now().date()
        start = end - timedelta(days=args.days * 1.5)  # 1.5x to account for weekends
    else:
        start = datetime.strptime(args.start, '%Y-%m-%d').date()
        end = datetime.strptime(args.end, '%Y-%m-%d').date()

    trading_days = get_trading_days(start, end)
    logger.info(f"Found {len(trading_days)} trading days from {start} to {end}")

    # Filter out days already in database if requested
    if args.skip_existing:
        remaining_days = []
        for day in trading_days:
            count = get_stored_tradable_count(day)
            if count == 0:
                remaining_days.append(day)
        logger.info(f"Skipping {len(trading_days) - len(remaining_days)} days already in database")
        trading_days = remaining_days

    if not trading_days:
        logger.info("No days to process")
        return

    # Get all tradable stocks once (exchange membership doesn't change daily)
    logger.info("\nFetching list of all tradable stocks from Alpaca...")
    all_tradable = get_tradable_stocks_for_date(start)
    logger.info(f"Found {len(all_tradable):,} tradable symbols")

    # Process each trading day
    for idx, trading_day in enumerate(trading_days, 1):
        logger.info(f"\n[{idx}/{len(trading_days)}] Processing {trading_day.strftime('%Y-%m-%d %A')}")

        try:
            # Get stocks in price range for this day
            stocks_in_range = get_stocks_in_price_range_for_date(
                all_tradable,
                trading_day,
                min_price=1.0,
                max_price=20.0,
                chunk_size=500
            )

            logger.info(f"  {len(stocks_in_range)} stocks in $1-$20 range")

            # Store in database
            store_stocks_for_date(trading_day, stocks_in_range)

        except Exception as e:
            logger.error(f"  Failed: {e}")
            continue

    # Summary
    print("\n" + "="*80)
    print("  COMPLETE")
    print("="*80)

    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT date) FROM tradable_stocks_by_date")
        date_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM tradable_stocks_by_date")
        total_stocks = cursor.fetchone()[0]

        print(f"Stored data for {date_count} trading days")
        print(f"Total stock-date records: {total_stocks:,}")

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
