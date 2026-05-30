#!/usr/bin/env python3
"""
Fetch stocks in a price range (default: $1-$20)
Creates a symbol list for backfill and ongoing tracking.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockSnapshotRequest
from config import Config
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def get_all_tradable_stocks():
    """Get all active, tradable stocks from Alpaca"""
    import time

    logger.info("=" * 70)
    logger.info("STEP 1: Fetching all tradable stocks from Alpaca...")
    logger.info("=" * 70)
    logger.info("This may take 30-60 seconds...")

    start = time.time()

    client = TradingClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY,
        paper=(Config.TRADING_MODE == 'PAPER'),
    )

    logger.info("Calling Alpaca API...")
    assets = client.get_all_assets()
    logger.info(f"Received {len(assets):,} total assets in {time.time()-start:.1f}s")

    # Filter for active, tradable stocks on major exchanges
    logger.info("Filtering for tradable US equities on major exchanges...")
    tradable = [
        a for a in assets
        if a.tradable
        and a.status == 'active'
        and a.exchange in ['NASDAQ', 'NYSE', 'ARCA', 'AMEX']
        and a.asset_class == 'us_equity'
    ]

    logger.info(f"[COMPLETE] Found {len(tradable):,} tradable stocks")
    return [a.symbol for a in tradable]

def get_stocks_in_price_range(symbols, min_price=1.0, max_price=20.0, chunk_size=500):
    """Filter stocks by current price range"""
    import time

    logger.info(f"Filtering for stocks between ${min_price} and ${max_price}...")
    logger.info(f"Total symbols to check: {len(symbols):,}")

    total_chunks = (len(symbols) - 1) // chunk_size + 1
    logger.info(f"Will process in {total_chunks} chunks of {chunk_size} symbols each")

    client = StockHistoricalDataClient(
        Config.ALPACA_API_KEY,
        Config.ALPACA_SECRET_KEY
    )

    in_range = []
    start_time = time.time()

    # Process in chunks
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i + chunk_size]
        chunk_num = i // chunk_size + 1

        logger.info(f"\n[Chunk {chunk_num}/{total_chunks}] Processing {len(chunk)} symbols...")

        try:
            chunk_start = time.time()
            request = StockSnapshotRequest(symbol_or_symbols=chunk)
            snapshots = client.get_stock_snapshot(request)
            chunk_time = time.time() - chunk_start

            logger.info(f"  API call completed in {chunk_time:.1f}s")
            logger.info(f"  Received {len(snapshots)} snapshots")

            chunk_matches = 0
            for symbol, snapshot in snapshots.items():
                if snapshot.latest_trade and snapshot.latest_trade.price:
                    price = snapshot.latest_trade.price
                    if min_price <= price <= max_price:
                        in_range.append({
                            'symbol': symbol,
                            'price': round(price, 2)
                        })
                        chunk_matches += 1

            logger.info(f"  Found {chunk_matches} stocks in price range")
            logger.info(f"  Total so far: {len(in_range)} stocks")

            # Calculate ETA
            elapsed = time.time() - start_time
            avg_per_chunk = elapsed / chunk_num
            remaining = (total_chunks - chunk_num) * avg_per_chunk
            logger.info(f"  Elapsed: {elapsed/60:.1f}min | ETA: {remaining/60:.1f}min")

        except Exception as e:
            logger.error(f"  [ERROR] Failed to fetch chunk {chunk_num}: {e}")
            logger.error(f"  Skipping this chunk and continuing...")
            continue

    # Sort by price
    in_range.sort(key=lambda x: x['price'])

    total_time = time.time() - start_time
    logger.info(f"\n[COMPLETE] Found {len(in_range):,} stocks between ${min_price}-${max_price}")
    logger.info(f"Total time: {total_time/60:.1f} minutes")
    return in_range

def save_symbol_list(stocks, filename='stocks_in_price_range.json'):
    """Save symbol list to file"""
    from datetime import datetime
    filepath = os.path.join(os.path.dirname(__file__), filename)

    data = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'count': len(stocks),
        'stocks': stocks,
        'symbols_only': [s['symbol'] for s in stocks]
    }

    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

    logger.info(f"Saved {len(stocks)} stocks to {filepath}")

    # Also save just symbols to a simple text file
    txt_file = filepath.replace('.json', '.txt')
    with open(txt_file, 'w') as f:
        for stock in stocks:
            f.write(f"{stock['symbol']}\n")

    logger.info(f"Saved symbols list to {txt_file}")

    return filepath

def estimate_data_volume(num_stocks, days=14):
    """Estimate storage and API calls"""
    print("\n" + "=" * 70)
    print("  DATA VOLUME ESTIMATES")
    print("=" * 70)

    # Minute candles
    minutes_per_day = 870  # 4am-8pm extended hours
    minute_candles = num_stocks * days * minutes_per_day
    minute_storage_mb = minute_candles * 0.0001  # ~100 bytes per candle

    # Daily candles
    daily_candles = num_stocks * days
    daily_storage_mb = daily_candles * 0.0001

    # Hour candles
    hour_candles = num_stocks * days * 16  # 16 hours/day
    hour_storage_mb = hour_candles * 0.0001

    print(f"\nFor {num_stocks:,} stocks over {days} days:")
    print("\nMinute Candles:")
    print(f"  Total candles: {minute_candles:,}")
    print(f"  Storage: ~{minute_storage_mb:.0f} MB")
    print(f"  Backfill time: ~{num_stocks * 0.5:.0f} minutes ({num_stocks * 0.5 / 60:.1f} hours)")

    print("\nDaily Candles (60 days):")
    print(f"  Total candles: {num_stocks * 60:,}")
    print(f"  Storage: ~{num_stocks * 60 * 0.0001:.0f} MB")
    print(f"  Backfill time: ~{num_stocks * 0.05:.0f} minutes")

    print("\nHour Candles:")
    print(f"  Total candles: {hour_candles:,}")
    print(f"  Storage: ~{hour_storage_mb:.0f} MB")
    print(f"  Backfill time: ~{num_stocks * 0.1:.0f} minutes")

    total_storage = minute_storage_mb + daily_storage_mb + hour_storage_mb
    print(f"\nTotal Storage: ~{total_storage:.0f} MB ({total_storage/1024:.1f} GB)")
    print("=" * 70 + "\n")

def main():
    """Main function"""
    print("\n" + "=" * 70)
    print("  FETCH STOCKS IN PRICE RANGE")
    print("=" * 70)

    # Step 1: Get all tradable stocks
    all_stocks = get_all_tradable_stocks()

    # Step 2: Filter by price range ($1-$20)
    stocks_1_to_20 = get_stocks_in_price_range(all_stocks, min_price=1.0, max_price=20.0)

    # Step 3: Show results
    print(f"\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}")
    print(f"\nTotal stocks between $1-$20: {len(stocks_1_to_20):,}")

    if stocks_1_to_20:
        print(f"\nPrice distribution:")
        range_1_5 = len([s for s in stocks_1_to_20 if 1 <= s['price'] < 5])
        range_5_10 = len([s for s in stocks_1_to_20 if 5 <= s['price'] < 10])
        range_10_15 = len([s for s in stocks_1_to_20 if 10 <= s['price'] < 15])
        range_15_20 = len([s for s in stocks_1_to_20 if 15 <= s['price'] <= 20])

        print(f"  $1 - $5:    {range_1_5:,} stocks")
        print(f"  $5 - $10:   {range_5_10:,} stocks")
        print(f"  $10 - $15:  {range_10_15:,} stocks")
        print(f"  $15 - $20:  {range_15_20:,} stocks")

        print(f"\nSample (first 20):")
        for stock in stocks_1_to_20[:20]:
            print(f"  {stock['symbol']:6s} ${stock['price']:6.2f}")

        if len(stocks_1_to_20) > 20:
            print(f"  ... and {len(stocks_1_to_20) - 20:,} more")

    # Step 4: Estimate data volume
    estimate_data_volume(len(stocks_1_to_20), days=14)

    # Step 5: Save to file
    filepath = save_symbol_list(stocks_1_to_20)

    print("\n" + "=" * 70)
    print("  NEXT STEPS")
    print("=" * 70)
    print(f"\n1. Review the list: {filepath}")
    print(f"2. Use this list for backfill:")
    print(f"   - Edit database/backfill_historical.py")
    print(f"   - Replace Config.DEBUG_STOCKS with symbols from this file")
    print(f"3. Consider starting with fewer stocks for testing (e.g., first 200)")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Cancelled by user")
    except Exception as e:
        logger.error(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
