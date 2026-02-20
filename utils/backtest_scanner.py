#!/usr/bin/env python3
"""
Backtest Stock Scanner Strategy
Run the scanner logic against historical data to test performance.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.query_helpers import StockDataDB, get_backtest_data
from backend.news_fetcher import NewsFetcher
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
    'min_price': 1.0,               # was 2.0 - allow gappers/penny stocks
    'max_price': 20.0,              # Ross Cameron v2 p4: $2-$20 sweet spot (adjusted)
    'min_morning_volume': 100_000,  # 9am-12pm volume
    'min_relative_volume': 3.0,     # was 5.0 - will revert to 5 after data maturity
                                    # Ross v2 p4: 5x minimum (10x+ preferred)
    'min_premarket_gain': 10.0,     # Ross v2 p4: up 10%+ from prior close
    'max_float': 50_000_000,        # was 20M - relax to allow more small caps
    'max_market_cap': 500_000_000,  # Ross v2 p5: <$500M (small/micro-cap)
    'max_spread': 0.15,             # Ross v2 p9: <10-15 cents spread
}


def passes_filters(data, debug_first_n=None):
    """
    Apply scanner filters to stock data.

    Args:
        data: Dict from get_backtest_data()
        debug_first_n: If set, log detailed debug info for first N symbols (e.g., 5)

    Returns:
        (passes: bool, reason: str)
    """
    symbol = data['symbol']
    debug = debug_first_n is not None and debug_first_n > 0

    if debug:
        logger.info(f"  [DEBUG] {symbol}: Checking filters...")

    # Get latest price from daily bars
    if not data['daily_bars']:
        reason = "No daily data"
        if debug:
            logger.info(f"    ❌ {reason}")
        return False, reason

    latest_price = data['daily_bars'][-1]['close']

    if debug:
        logger.info(f"    Price: ${latest_price:.2f} (range: ${CRITERIA['min_price']:.2f}-${CRITERIA['max_price']:.2f})")

    # Price filter
    if latest_price < CRITERIA['min_price'] or latest_price > CRITERIA['max_price']:
        reason = f"Price ${latest_price:.2f} outside range"
        if debug:
            logger.info(f"    ❌ {reason}")
        return False, reason

    # NOTE: We don't filter on average volume anymore.
    # Low average volume + high current volume = strong momentum signal.
    # We use average volume ONLY for calculating relative volume.

    # Volume filter - use total (premarket + market) so pre-9:30am scans work
    total_volume = data.get('total_volume', data.get('morning_volume', 0))
    min_morning = CRITERIA['min_morning_volume']
    if debug:
        logger.info(f"    Total Volume: {total_volume:,} (min: {min_morning:,})")

    if total_volume < min_morning:
        reason = f"Total volume {total_volume:,} < {min_morning:,}"
        if debug:
            logger.info(f"    ❌ {reason}")
        return False, reason

    # Relative volume filter
    rel_vol = data['relative_volume']
    min_rel = CRITERIA['min_relative_volume']
    if debug:
        logger.info(f"    Relative Volume: {rel_vol:.2f}x (min: {min_rel:.2f}x)")

    if rel_vol < min_rel:
        reason = f"Relative volume {rel_vol:.2f}x < {min_rel:.2f}x"
        if debug:
            logger.info(f"    ❌ {reason}")
        return False, reason

    # Premarket gain filter
    pct = data['pct_change']
    min_pct = CRITERIA['min_premarket_gain']
    if debug:
        logger.info(f"    % Change: {pct:.2f}% (min: {min_pct:.2f}%)")

    if pct < min_pct:
        reason = f"% change {pct:.2f}% < {min_pct:.2f}%"
        if debug:
            logger.info(f"    ❌ {reason}")
        return False, reason

    # Float filter (Ross v2 p4: Pillar 4 — <20M shares)
    # Skip gracefully if no fundamentals data in DB yet (run fetch_fundamentals.py first)
    fund = data.get('fundamentals')
    if fund and fund.get('float_shares'):
        float_val = fund['float_shares']
        max_float = CRITERIA['max_float']
        if debug:
            logger.info(f"    Float: {float_val/1e6:.1f}M (max: {max_float/1e6:.1f}M)")

        if float_val > max_float:
            reason = f"Float {float_val/1e6:.1f}M > {max_float/1e6:.0f}M max"
            if debug:
                logger.info(f"    ❌ {reason}")
            return False, reason

    # Market cap filter (Ross v2 p5: <$500M)
    if fund and fund.get('market_cap'):
        mktcap = fund['market_cap']
        max_mktcap = CRITERIA['max_market_cap']
        if debug:
            logger.info(f"    Market Cap: ${mktcap/1e6:.0f}M (max: ${max_mktcap/1e6:.0f}M)")

        if mktcap > max_mktcap:
            reason = f"Market cap ${mktcap/1e6:.0f}M > ${max_mktcap/1e6:.0f}M max"
            if debug:
                logger.info(f"    ❌ {reason}")
            return False, reason

    # Spread filter (Ross v2 p9: <10-15 cents — live mode only, bid/ask from snapshot)
    spread = data.get('spread')
    if spread is not None:
        max_spread = CRITERIA['max_spread']
        if debug:
            logger.info(f"    Spread: ${spread:.2f} (max: ${max_spread:.2f})")

        if spread > max_spread:
            reason = f"Spread ${spread:.2f} > ${max_spread:.2f} max"
            if debug:
                logger.info(f"    ❌ {reason}")
            return False, reason

    if debug:
        logger.info(f"    ✅ ALL FILTERS PASSED!")

    return True, "PASS"


def backtest_single_day(date, max_stocks=None, scan_time=None, progress_callback=None):
    """
    Run scanner on a single trading day (OPTIMIZED - batch queries).

    Args:
        date: datetime.date to backtest
        max_stocks: Limit number of stocks to test (None = all)
        scan_time: Optional datetime.time for backtest (e.g., 09:00). If not provided, uses end of day.
        progress_callback: Optional fn(stage, message, pct) for frontend status updates

    Returns:
        Dict with scan results
    """
    import time as _time
    scan_start = _time.time()

    def report(stage, msg, pct):
        elapsed = _time.time() - scan_start
        logger.info(f"[Stage {stage}] [{elapsed:.1f}s] {msg}")
        if progress_callback:
            progress_callback(stage, msg, pct)

    logger.info(f"\n{'='*70}")
    time_str = f" @ {scan_time.strftime('%H:%M')}" if scan_time else ""
    logger.info(f"BACKTESTING: {date.strftime('%Y-%m-%d (%A)')}{time_str}")
    logger.info(f"{'='*70}")

    with StockDataDB() as db:
        # Get all symbols with data on this date
        report(1, f"Looking up symbols with data for {date}...", 5)
        symbols = db.get_symbols_with_data(date)

        if not symbols:
            report(1, f"No data found for {date} — collector may not have run yet.", 0)
            return {'date': date, 'total_tested': 0, 'passed': [], 'failed': [],
                    'error': f'No data in database for {date}. Is the collector running?'}

        if max_stocks:
            symbols = symbols[:max_stocks]

        report(1, f"Found {len(symbols):,} symbols with data for {date}", 10)
        logger.info(f"Fetching data in batches...")

        # What time is it in ET?
        # - For specific backtest time: use provided time
        # - For live scans: use current time
        # - For end-of-day backtest: use end of day
        if scan_time:
            # Backtest at specific time - combine date and time in ET
            now_et = ET.localize(datetime.combine(date, scan_time))
        else:
            now_et = datetime.now(ET)
            if now_et.date() != date:
                # Historical backtest - use end of day
                now_et = ET.localize(datetime.combine(date, datetime.max.time()))

        if now_et.date() == date and not scan_time:
            # Live scan - use the actual current time as the cutoff
            scan_hour   = now_et.hour
            scan_minute = now_et.minute
        else:
            # Backtest - use end of trading day (8pm) to get all data
            scan_hour, scan_minute = 20, 0

        logger.info(f"Scan window: 4:00 AM → {scan_hour:02d}:{scan_minute:02d} ET")

        # BATCH QUERY 1: Get all daily bars for all symbols (1 query)
        report(2, f"Fetching 30-day daily bars for {len(symbols):,} symbols...", 20)
        start_date = date - timedelta(days=30)
        daily_data_all = db.get_daily_bars(symbols, start_date, date)
        report(2, f"Daily bars loaded for {len(daily_data_all):,} symbols", 35)

        # BATCH QUERY 2: Get all minute bars for all symbols up to scan time (1 query)
        report(3, f"Fetching today's minute bars (4am-{scan_hour:02d}:{scan_minute:02d})...", 40)
        minute_data_all = db.get_minute_bars(symbols, date, start_hour=4, end_hour=scan_hour + 1)
        report(3, f"Minute bars loaded for {len(minute_data_all):,} symbols", 55)

        # BATCH QUERY 3: Historical avg volume at this same time of day (1 query)
        report(4, f"Fetching historical same-time volume averages...", 60)
        avg_at_time = db.get_avg_volume_at_time_batch(
            symbols, date, scan_hour, scan_minute, lookback_days=20
        )
        logger.info(f"Historical same-time avg fetched for {len(avg_at_time):,} symbols")

        # BATCH QUERY 4: Fundamentals (float + market cap) from stock_fundamentals table
        # Graceful: if table doesn't exist yet, return empty dict so scanner still works
        try:
            fundamentals_all = db.get_fundamentals_batch(symbols)
            logger.info(f"Fundamentals loaded for {len(fundamentals_all):,} symbols")
        except Exception as e:
            logger.warning(f"Could not load fundamentals (run fetch_fundamentals.py first): {e}")
            fundamentals_all = {}

        report(5, f"Applying filters to {len(symbols):,} symbols...", 65)
        logger.info(f"[DEBUG] Logging first 10 symbols to identify filter bottleneck")

        passed = []
        failed = []

        for i, symbol in enumerate(symbols):
            if (i + 1) % 500 == 0:
                pct_done = 65 + int(25 * (i + 1) / len(symbols))
                report(5, f"Filtering symbols... {i+1:,}/{len(symbols):,}", pct_done)

            try:
                # Get this symbol's data from batch results
                daily_bars = daily_data_all.get(symbol, [])
                minute_bars = minute_data_all.get(symbol, [])

                # Calculate metrics from batched data
                if not daily_bars:
                    failed.append({'symbol': symbol, 'reason': 'No daily data'})
                    continue

                # Calculate avg volume (last 20 days from daily bars)
                recent_bars = daily_bars[-20:] if len(daily_bars) >= 20 else daily_bars
                avg_volume = sum(bar['volume'] for bar in recent_bars) // len(recent_bars) if recent_bars else 0

                # Split minute bars into pre-market (4am-9:30am) and market hours (9:30am+)
                premarket_bars = [b for b in minute_bars if b['hour'] < 9 or (b['hour'] == 9 and b['minute'] < 30)]
                market_bars    = [b for b in minute_bars if b['hour'] > 9 or (b['hour'] == 9 and b['minute'] >= 30)]

                premarket_volume = sum(bar['volume'] for bar in premarket_bars)
                morning_volume   = sum(bar['volume'] for bar in market_bars)
                total_volume     = premarket_volume + morning_volume

                # Relative volume (Ross Cameron style):
                # Volume so far today / Average volume at this same time of day historically
                # This correctly represents "is volume unusually high right now?"
                avg_vol_at_time = avg_at_time.get(symbol, 0)
                relative_volume = total_volume / avg_vol_at_time if avg_vol_at_time > 0 else 0.0

                # Premarket gain: % change vs prior day's close
                # If the last daily bar is for today, prior close is daily_bars[-2]
                # Otherwise (live mode, today's bar not yet in 1d table), it's daily_bars[-1]
                last_daily_time = daily_bars[-1]['time']
                last_daily_date = last_daily_time.date() if hasattr(last_daily_time, 'date') else last_daily_time
                if last_daily_date == date and len(daily_bars) >= 2:
                    prior_close = float(daily_bars[-2]['close'])
                else:
                    prior_close = float(daily_bars[-1]['close'])

                # Current price: last minute bar close, or fall back to latest daily close
                current_price = float(minute_bars[-1]['close']) if minute_bars else prior_close
                pct_change = ((current_price - prior_close) / prior_close * 100) if prior_close > 0 else 0.0

                # Build data dict for filter
                data = {
                    'symbol': symbol,
                    'daily_bars': daily_bars,
                    'minute_bars': minute_bars,
                    'avg_volume': avg_volume,
                    'premarket_volume': premarket_volume,
                    'morning_volume': morning_volume,  # market-hours volume (9:30am+)
                    'total_volume': total_volume,
                    'relative_volume': relative_volume,
                    'pct_change': pct_change,
                    'prior_close': prior_close,
                    'current_price': current_price,
                    'fundamentals': fundamentals_all.get(symbol),
                    'spread': None,  # populated after filtering for live mode
                }

                # Apply filters (debug first 10 symbols)
                debug_this = 10 if i < 10 else None
                passes, reason = passes_filters(data, debug_first_n=debug_this)

                if passes:
                    fund = fundamentals_all.get(symbol) or {}
                    passed.append({
                        'symbol': symbol,
                        'price': round(current_price, 2),
                        'prior_close': round(prior_close, 2),
                        'pct_change': round(pct_change, 2),
                        'avg_volume': int(avg_volume),
                        'premarket_volume': int(premarket_volume),
                        'morning_volume': int(morning_volume),
                        'total_volume': int(total_volume),
                        'relative_volume': round(float(relative_volume), 2),
                        'float_shares': fund.get('float_shares'),
                        'market_cap': fund.get('market_cap'),
                        'company_name': fund.get('company_name', ''),
                        'spread': None,   # enriched below for live scans
                        'bid': None,
                        'ask': None,
                    })
                else:
                    failed.append({'symbol': symbol, 'reason': reason})

            except Exception as e:
                logger.warning(f"  [WARN] {symbol}: {e}")
                failed.append({'symbol': symbol, 'reason': f"Error: {e}"})

        # Enrich with live spread (bid/ask) from Alpaca snapshots — LIVE MODE ONLY
        # Only 5-20 stocks typically pass all filters, so this is a fast single batch call.
        is_live = (now_et.date() == date)
        if is_live and passed:
            try:
                import sys as _sys
                _sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
                from backend.data_feed import AlpacaDataFeed
                feed = AlpacaDataFeed()
                passing_symbols = [s['symbol'] for s in passed]
                snapshots = feed.get_batch_snapshots(passing_symbols)
                for stock in passed:
                    snap = snapshots.get(stock['symbol'])
                    if snap and snap.latest_quote:
                        bid = snap.latest_quote.bid_price
                        ask = snap.latest_quote.ask_price
                        if bid and ask:
                            stock['bid']    = round(bid, 4)
                            stock['ask']    = round(ask, 4)
                            stock['spread'] = round(ask - bid, 4)
                logger.info(f"Spread enriched for {len(passing_symbols)} live candidates")
            except Exception as e:
                logger.warning(f"Could not fetch live spread data: {e}")

        # Fetch news for all passing stocks
        if passed:
            logger.info(f"Fetching news for {len(passed)} passing stocks...")
            try:
                news_fetcher = NewsFetcher()
                for stock in passed:
                    has_cat, articles = news_fetcher.has_catalyst(stock['symbol'], as_of_date=date)
                    stock['has_catalyst'] = has_cat
                    stock['news'] = articles[:3]  # Top 3 headlines
                    stock['news_count'] = len(articles)
            except Exception as e:
                logger.warning(f"News fetch failed: {e} - continuing without news")
                for stock in passed:
                    stock['has_catalyst'] = None
                    stock['news'] = []
                    stock['news_count'] = 0

        # Sort by relative volume (highest first)
        passed.sort(key=lambda x: x['relative_volume'], reverse=True)

        elapsed = _time.time() - scan_start
        report(6, f"Scan complete: {len(passed)} stocks passed filters ({elapsed:.1f}s total)", 100)
        logger.info(f"✅ Scan complete: {len(passed)} passed, {len(failed)} failed")

        # Analyze failure reasons
        if failed:
            from collections import Counter
            failure_reasons = Counter(f['reason'] for f in failed)
            logger.info(f"\n[FAILURE BREAKDOWN]")
            for reason, count in failure_reasons.most_common(10):
                pct = (count / len(failed)) * 100
                logger.info(f"  {pct:5.1f}% ({count:4d}) — {reason}")

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

        print(f"\n{'Symbol':<8} {'Price':<8} {'Chg%':<8} {'Avg Vol':<12} {'AM Vol':<12} {'Rel Vol':<10}")
        print("-" * 78)

        for stock in passed[:20]:  # Show top 20
            chg = stock.get('pct_change', 0)
            sign = '+' if chg >= 0 else ''
            print(f"{stock['symbol']:<8} "
                  f"${stock['price']:<7.2f} "
                  f"{sign}{chg:<6.1f}% "
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
