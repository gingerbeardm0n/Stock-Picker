#!/usr/bin/env python3
"""
Backtest Stock Scanner Strategy
Run the scanner logic against historical data to test performance.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database.query_helpers import StockDataDB, get_backtest_data
from datetime import datetime, timedelta
import pytz
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')


# ============================================================================
# SCANNER CRITERIA (Same as live scanner)
# ============================================================================

CRITERIA = {
    'min_price': 1.0,
    'max_price': 10.0,
    'min_avg_volume': 500_000,      # 20-day average
    'min_morning_volume': 100_000,  # 9am-12pm volume
    'min_relative_volume': 2.0,     # 2x average at this time
}


def passes_filters(data):
    """
    Apply scanner filters to stock data.

    Args:
        data: Dict from get_backtest_data()

    Returns:
        (passes: bool, reason: str)
    """
    symbol = data['symbol']

    # Get latest price from daily bars
    if not data['daily_bars']:
        return False, "No daily data"

    latest_price = data['daily_bars'][-1]['close']

    # Price filter
    if latest_price < CRITERIA['min_price'] or latest_price > CRITERIA['max_price']:
        return False, f"Price ${latest_price:.2f} outside range"

    # Average volume filter
    if data['avg_volume'] < CRITERIA['min_avg_volume']:
        return False, f"Avg volume {data['avg_volume']:,} too low"

    # Morning volume filter
    if data['morning_volume'] < CRITERIA['min_morning_volume']:
        return False, f"Morning volume {data['morning_volume']:,} too low"

    # Relative volume filter
    if data['relative_volume'] < CRITERIA['min_relative_volume']:
        return False, f"Relative volume {data['relative_volume']:.1f}x too low"

    return True, "PASS"


def backtest_single_day(date, max_stocks=None):
    """
    Run scanner on a single trading day (OPTIMIZED - batch queries).

    Args:
        date: datetime.date to backtest
        max_stocks: Limit number of stocks to test (None = all)

    Returns:
        Dict with scan results
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"BACKTESTING: {date.strftime('%Y-%m-%d (%A)')}")
    logger.info(f"{'='*70}")

    with StockDataDB() as db:
        # Get all symbols with data on this date
        symbols = db.get_symbols_with_data(date)

        if max_stocks:
            symbols = symbols[:max_stocks]

        logger.info(f"Testing {len(symbols):,} symbols...")
        logger.info(f"Fetching data in batches...")

        # BATCH QUERY 1: Get all daily bars for all symbols (1 query)
        start_date = date - timedelta(days=30)
        daily_data_all = db.get_daily_bars(symbols, start_date, date)

        # BATCH QUERY 2: Get all minute bars for all symbols (1 query)
        minute_data_all = db.get_minute_bars(symbols, date, start_hour=9, end_hour=12)

        # Calculate noon ET for relative volume
        noon_et = ET.localize(datetime.combine(date, datetime.min.time().replace(hour=12)))

        logger.info(f"Processing {len(symbols):,} symbols...")

        passed = []
        failed = []

        for i, symbol in enumerate(symbols):
            if (i + 1) % 500 == 0:
                logger.info(f"  Progress: {i+1}/{len(symbols)} symbols processed")

            try:
                # Get this symbol's data from batch results
                daily_bars = daily_data_all.get(symbol, [])
                minute_bars = minute_data_all.get(symbol, [])

                # Calculate metrics from batched data
                if not daily_bars:
                    failed.append({'symbol': symbol, 'reason': 'No daily data'})
                    continue

                # Calculate avg volume (last 20 days)
                recent_bars = daily_bars[-20:] if len(daily_bars) >= 20 else daily_bars
                avg_volume = sum(bar['volume'] for bar in recent_bars) // len(recent_bars) if recent_bars else 0

                # Calculate morning volume (sum minute bars)
                morning_volume = sum(bar['volume'] for bar in minute_bars)

                # Calculate relative volume (similar to query_helpers method)
                # Today's volume up to noon
                today_volume = morning_volume

                # Average volume at noon over past 30 days (use daily bars as proxy)
                # This is simplified - assumes uniform distribution throughout day
                # Real calculation would need historical minute data for same time
                avg_daily_volume = avg_volume
                avg_volume_at_noon = avg_daily_volume * 0.5  # Rough estimate: 50% by noon

                relative_volume = today_volume / avg_volume_at_noon if avg_volume_at_noon > 0 else 0.0

                # Build data dict for filter
                data = {
                    'symbol': symbol,
                    'daily_bars': daily_bars,
                    'minute_bars': minute_bars,
                    'avg_volume': avg_volume,
                    'morning_volume': morning_volume,
                    'relative_volume': relative_volume
                }

                # Apply filters
                passes, reason = passes_filters(data)

                if passes:
                    passed.append({
                        'symbol': symbol,
                        'price': float(daily_bars[-1]['close']),  # Convert Decimal to float
                        'avg_volume': int(avg_volume),
                        'morning_volume': int(morning_volume),
                        'relative_volume': round(float(relative_volume), 2)
                    })
                else:
                    failed.append({'symbol': symbol, 'reason': reason})

            except Exception as e:
                logger.warning(f"  [WARN] {symbol}: {e}")
                failed.append({'symbol': symbol, 'reason': f"Error: {e}"})

        # Sort by relative volume (highest first)
        passed.sort(key=lambda x: x['relative_volume'], reverse=True)

        logger.info(f"✅ Scan complete: {len(passed)} passed, {len(failed)} failed")

        return {
            'date': date,
            'total_tested': len(symbols),
            'passed': passed,
            'failed': failed
        }


def print_results(results):
    """Print backtest results in readable format"""
    date = results['date']
    passed = results['passed']
    failed = results['failed']

    logger.info(f"\n{'='*70}")
    logger.info(f"RESULTS FOR {date.strftime('%Y-%m-%d')}")
    logger.info(f"{'='*70}")

    logger.info(f"\nTotal tested: {results['total_tested']:,}")
    logger.info(f"✅ Passed filters: {len(passed)}")
    logger.info(f"❌ Failed filters: {len(failed)}")

    if passed:
        logger.info(f"\n{'='*70}")
        logger.info(f"TOP CANDIDATES (Sorted by Relative Volume)")
        logger.info(f"{'='*70}")

        print(f"\n{'Symbol':<8} {'Price':<8} {'Avg Vol':<12} {'AM Vol':<12} {'Rel Vol':<10}")
        print("-" * 70)

        for stock in passed[:20]:  # Show top 20
            print(f"{stock['symbol']:<8} "
                  f"${stock['price']:<7.2f} "
                  f"{stock['avg_volume']:>11,} "
                  f"{stock['morning_volume']:>11,} "
                  f"{stock['relative_volume']:>9.1f}x")

        if len(passed) > 20:
            logger.info(f"\n... and {len(passed) - 20} more candidates")
    else:
        logger.info("\n⚠️ No stocks passed all filters on this date")


def backtest_date_range(start_date, end_date, max_stocks_per_day=None):
    """
    Run backtest across multiple trading days.

    Args:
        start_date: Start date
        end_date: End date
        max_stocks_per_day: Limit stocks tested per day (None = all)

    Returns:
        List of daily results
    """
    logger.info(f"{'='*70}")
    logger.info(f"BACKTEST DATE RANGE")
    logger.info(f"{'='*70}")
    logger.info(f"Start: {start_date}")
    logger.info(f"End: {end_date}")

    with StockDataDB() as db:
        trading_days = db.get_trading_days(start_date, end_date)

    logger.info(f"Trading days: {len(trading_days)}")

    all_results = []

    for trade_date in trading_days:
        results = backtest_single_day(trade_date, max_stocks=max_stocks_per_day)
        print_results(results)
        all_results.append(results)

    # Summary across all days
    logger.info(f"\n{'='*70}")
    logger.info(f"BACKTEST SUMMARY")
    logger.info(f"{'='*70}")

    total_candidates = sum(len(r['passed']) for r in all_results)
    avg_candidates = total_candidates / len(all_results) if all_results else 0

    logger.info(f"Total trading days: {len(all_results)}")
    logger.info(f"Total candidates found: {total_candidates}")
    logger.info(f"Average per day: {avg_candidates:.1f}")

    # Days with most candidates
    sorted_days = sorted(all_results, key=lambda x: len(x['passed']), reverse=True)

    logger.info(f"\nTop 5 days (most candidates):")
    for r in sorted_days[:5]:
        logger.info(f"  {r['date']}: {len(r['passed'])} candidates")

    return all_results


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Interactive backtesting"""

    print("\n" + "="*70)
    print("  STOCK SCANNER BACKTESTING")
    print("="*70)
    print("\nCurrent Criteria:")
    print(f"  Price: ${CRITERIA['min_price']:.2f} - ${CRITERIA['max_price']:.2f}")
    print(f"  Avg Volume: {CRITERIA['min_avg_volume']:,}+")
    print(f"  Morning Volume: {CRITERIA['min_morning_volume']:,}+")
    print(f"  Relative Volume: {CRITERIA['min_relative_volume']:.1f}x+")

    print("\nSelect backtest mode:")
    print("  1. Single day (quick test)")
    print("  2. Date range (full backtest)")
    print("  3. Last 5 trading days")

    choice = input("\nEnter choice (1/2/3): ").strip()

    if choice == "1":
        # Single day
        date_str = input("Enter date (YYYY-MM-DD) or press Enter for latest: ").strip()

        if date_str:
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            # Get latest trading day from database
            with StockDataDB() as db:
                trading_days = db.get_trading_days(
                    datetime.now().date() - timedelta(days=30),
                    datetime.now().date()
                )
                date = trading_days[-1] if trading_days else datetime.now().date()

        results = backtest_single_day(date)
        print_results(results)

    elif choice == "2":
        # Date range
        start_str = input("Start date (YYYY-MM-DD): ").strip()
        end_str = input("End date (YYYY-MM-DD): ").strip()

        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()

        backtest_date_range(start_date, end_date)

    elif choice == "3":
        # Last 5 trading days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=10)  # Go back 10 days to catch 5 trading days

        backtest_date_range(start_date, end_date)

    else:
        logger.error("Invalid choice")
        return

    logger.info("\n✅ Backtest complete!")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n[STOPPED] Backtest cancelled by user")
    except Exception as e:
        logger.error(f"\n\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
