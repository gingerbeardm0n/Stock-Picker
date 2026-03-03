#!/usr/bin/env python3
"""
Scanner Sanity Check
====================
Validates our scanner results against independently-computed "ground truth" movers
from the same database. No external API needed -- all from local TimescaleDB data.

Usage:
    python maintenance/sanity_check.py 2026-02-13
    python maintenance/sanity_check.py 2026-02-17
    python maintenance/sanity_check.py          # defaults to most recent trading day

What it does:
  1. "Ground truth" pass: queries raw daily bars to find the actual top movers
     for the target date (highest % gain, decent volume)
  2. "Scanner" pass: runs our backtest_single_day() with Ross Cameron criteria
  3. Comparison:
     - True positives  [PASS] scanner found a real big mover
     - False negatives [MISS] scanner missed a real big mover -- shows which filter blocked it
     - False positives [WARN] scanner flagged a stock that barely moved
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.query_helpers import StockDataDB
from utils.backtest_scanner import backtest_single_day, CRITERIA
from datetime import datetime, timedelta

# -- Tuning --
TOP_N_GROUND_TRUTH = 30   # show the top N movers as ground truth
MIN_GT_PCT_CHANGE  = 10.0 # only care about moves >= 10%
MIN_GT_AVG_VOLUME  = 100_000  # ground truth: min avg volume (loose filter)


def get_ground_truth(db, date, top_n=TOP_N_GROUND_TRUTH):
    """
    Find the real top movers for the date using raw daily bars.
    Returns a list of dicts sorted by % change descending.
    """
    start_date = date - timedelta(days=30)
    end_date   = date + timedelta(days=1)  # get_daily_bars uses exclusive end

    symbols = db.get_symbols_with_data(date)
    if not symbols:
        return []

    print(f"  Fetching daily bars for {len(symbols):,} symbols...")
    daily_data = db.get_daily_bars(symbols, start_date, end_date)

    movers = []
    for symbol, bars in daily_data.items():
        if len(bars) < 2:
            continue

        # Find bars for the target date and the prior day
        target_bars = [b for b in bars if _bar_date(b) == date]
        prior_bars  = [b for b in bars if _bar_date(b) < date]

        if not target_bars or not prior_bars:
            continue

        today_bar  = target_bars[-1]
        prior_bar  = prior_bars[-1]

        prior_close = float(prior_bar['close'])
        today_close = float(today_bar['close'])
        today_vol   = int(today_bar['volume'])

        if prior_close <= 0:
            continue

        pct_change = (today_close - prior_close) / prior_close * 100

        # 20-day avg volume (from prior bars, excluding today)
        recent = prior_bars[-20:]
        avg_vol = sum(int(b['volume']) for b in recent) // len(recent) if recent else 0

        movers.append({
            'symbol':      symbol,
            'price':       round(today_close, 2),
            'prior_close': round(prior_close, 2),
            'pct_change':  round(pct_change, 2),
            'volume':      today_vol,
            'avg_volume':  avg_vol,
        })

    # Filter to stocks with meaningful moves and some liquidity
    movers = [m for m in movers
              if m['pct_change'] >= MIN_GT_PCT_CHANGE
              and m['avg_volume'] >= MIN_GT_AVG_VOLUME]

    # Sort by % change descending
    movers.sort(key=lambda x: x['pct_change'], reverse=True)
    return movers[:top_n]


def _bar_date(bar):
    t = bar['time']
    if hasattr(t, 'date'):
        return t.date()
    return t


def run_sanity_check(date):
    print(f"\n{'='*72}")
    print(f"  SANITY CHECK -- {date.strftime('%Y-%m-%d (%A)')}")
    print(f"{'='*72}")

    # -- Step 1: Ground truth from raw DB --
    print(f"\n[1/2] Computing ground truth from raw daily bars...")
    with StockDataDB() as db:
        ground_truth = get_ground_truth(db, date)

    if not ground_truth:
        print(f"  [!] No stocks with >={MIN_GT_PCT_CHANGE}% gain found for {date}.")
        print(f"      Is this a trading day? Does the DB have daily bars for this date?")
        return

    gt_symbols = {m['symbol'] for m in ground_truth}
    print(f"  Found {len(ground_truth)} stocks with >={MIN_GT_PCT_CHANGE}% gain:")
    print(f"  {'Symbol':<8} {'Price':>7} {'Chg%':>8} {'Volume':>12} {'AvgVol':>12}")
    print(f"  {'-'*52}")
    for m in ground_truth:
        print(f"  {m['symbol']:<8} ${m['price']:>6.2f} {m['pct_change']:>7.1f}%"
              f" {m['volume']:>12,} {m['avg_volume']:>12,}")

    # -- Step 2: Run our scanner --
    print(f"\n[2/2] Running scanner with Ross Cameron criteria...")
    print(f"  Criteria: price ${CRITERIA['min_price']}-${CRITERIA['max_price']}"
          f" | relVol >={CRITERIA['min_relative_volume']}x"
          f" | gain >={CRITERIA['min_premarket_gain']}%"
          f" | float <={CRITERIA['max_float']/1e6:.0f}M")

    results = backtest_single_day(date)
    scanner_passed = results['passed']
    scanner_failed = {f['symbol']: f['reason'] for f in results['failed']}
    scanner_symbols = {s['symbol'] for s in scanner_passed}

    # -- Step 3: Comparison --
    true_positives  = [m for m in ground_truth if m['symbol'] in scanner_symbols]
    false_negatives = [m for m in ground_truth if m['symbol'] not in scanner_symbols]
    false_positives = [s for s in scanner_passed if s['symbol'] not in gt_symbols]

    print(f"\n{'='*72}")
    print(f"  COMPARISON RESULTS")
    print(f"{'='*72}")
    print(f"  Ground truth movers (>={MIN_GT_PCT_CHANGE}%): {len(ground_truth)}")
    print(f"  Scanner passed:                            {len(scanner_passed)}")
    print(f"  [PASS] True positives  (scanner caught):   {len(true_positives)}")
    print(f"  [MISS] False negatives (scanner missed):   {len(false_negatives)}")
    print(f"  [WARN] False positives (found, <{MIN_GT_PCT_CHANGE}%):   {len(false_positives)}")

    # True Positives
    if true_positives:
        print(f"\n  [PASS] TRUE POSITIVES -- Scanner correctly caught these:")
        print(f"  {'Symbol':<8} {'Price':>7} {'Chg%':>8} {'RelVol':>8}")
        print(f"  {'-'*38}")
        for m in true_positives:
            sc = next((s for s in scanner_passed if s['symbol'] == m['symbol']), {})
            rvol = sc.get('relative_volume', 0)
            print(f"  {m['symbol']:<8} ${m['price']:>6.2f} {m['pct_change']:>7.1f}% {rvol:>7.1f}x")

    # False Negatives -- missed movers (most important for debugging)
    if false_negatives:
        print(f"\n  [MISS] FALSE NEGATIVES -- Real movers our scanner MISSED:")
        print(f"  {'Symbol':<8} {'Chg%':>8}  Filter that blocked it")
        print(f"  {'-'*60}")
        for m in false_negatives:
            reason = scanner_failed.get(m['symbol'], 'Not in scanner universe (no minute data)')
            print(f"  {m['symbol']:<8} {m['pct_change']:>7.1f}%  <- {reason}")

    # False Positives -- scanner found but daily gain was < threshold
    if false_positives:
        print(f"\n  [WARN] FALSE POSITIVES -- Scanner flagged, but <{MIN_GT_PCT_CHANGE}% daily gain:")
        print(f"  {'Symbol':<8} {'Price':>7} {'Chg%':>8} {'RelVol':>8}")
        print(f"  {'-'*38}")
        for s in false_positives[:10]:
            print(f"  {s['symbol']:<8} ${s['price']:>6.2f} {s['pct_change']:>7.1f}% {s['relative_volume']:>7.1f}x")

    # Summary score
    recall = len(true_positives) / len(ground_truth) * 100 if ground_truth else 0
    print(f"\n  Recall: {recall:.0f}% ({len(true_positives)}/{len(ground_truth)} real movers caught)")
    if false_negatives:
        top = false_negatives[0]
        print(f"  Top missed: {top['symbol']} (+{top['pct_change']:.1f}%)"
              f" -- {scanner_failed.get(top['symbol'], '?')}")

    print(f"\n{'='*72}\n")
    return {
        'true_positives':  true_positives,
        'false_negatives': false_negatives,
        'false_positives': false_positives,
        'recall': recall,
    }


def main():
    if len(sys.argv) > 1:
        date = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
    else:
        # Default to most recent trading day in DB (excluding today)
        with StockDataDB() as db:
            days = db.get_trading_days(
                datetime.now().date() - timedelta(days=30),
                datetime.now().date() - timedelta(days=1)
            )
        if not days:
            print("No trading days found in database.")
            return
        date = days[-1]
        print(f"No date specified -- using most recent completed trading day: {date}")

    run_sanity_check(date)


if __name__ == '__main__':
    main()
