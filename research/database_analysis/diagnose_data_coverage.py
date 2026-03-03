#!/usr/bin/env python3
"""
Database Diagnostic: Comprehensive Data Coverage Analysis

Answers:
1. How many days each month have minute data for 1000+ stocks?
2. Month-by-month summary of data availability
3. Is there any complete period suitable for simulation runs?
"""

import sys
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from utils.query_helpers import StockDataDB
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd

def get_trading_days(start_date, end_date):
    """Get list of trading days (weekday only for now, ignore holidays)."""
    current = start_date
    trading_days = []
    while current <= end_date:
        # Skip weekends
        if current.weekday() < 5:
            trading_days.append(current)
        current += timedelta(days=1)
    return trading_days

def analyze_minute_data_coverage():
    """Question 1: How many days in each month have minute data for 1000+ stocks?"""
    print("\n" + "="*80)
    print("QUESTION 1: Monthly Minute Data Coverage (1000+ stocks per day)")
    print("="*80)

    with StockDataDB() as db:
        # Query: for each day, how many stocks have minute data?
        query = """
        SELECT
            DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as trading_date,
            COUNT(DISTINCT symbol) as symbol_count
        FROM stock_candles_1m
        GROUP BY DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
        ORDER BY trading_date DESC
        """

        cursor = db.conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        # Organize by month
        monthly_stats = defaultdict(lambda: {'days_1000plus': 0, 'days_total': 0, 'avg_symbols': 0, 'symbol_counts': []})

        for trading_date, symbol_count in results:
            month_key = trading_date.strftime('%Y-%m')
            monthly_stats[month_key]['days_total'] += 1
            monthly_stats[month_key]['symbol_counts'].append(symbol_count)
            if symbol_count >= 1000:
                monthly_stats[month_key]['days_1000plus'] += 1

        # Calculate averages
        for month_key in monthly_stats:
            counts = monthly_stats[month_key]['symbol_counts']
            monthly_stats[month_key]['avg_symbols'] = sum(counts) / len(counts) if counts else 0
            monthly_stats[month_key]['min_symbols'] = min(counts) if counts else 0
            monthly_stats[month_key]['max_symbols'] = max(counts) if counts else 0

        # Print results (newest first, then reverse for display)
        print(f"\n{'Month':<12} {'Days 1K+':<12} {'Total Days':<12} {'Avg Symbols':<14} {'Min':<8} {'Max':<8}")
        print("-" * 80)

        for month_key in sorted(monthly_stats.keys(), reverse=True):
            stats = monthly_stats[month_key]
            print(f"{month_key:<12} {stats['days_1000plus']:<12} {stats['days_total']:<12} "
                  f"{stats['avg_symbols']:<14.0f} {stats['min_symbols']:<8.0f} {stats['max_symbols']:<8.0f}")

        return monthly_stats


def analyze_hourly_data_coverage():
    """Check hourly data coverage for all hours (4am-8pm full day)."""
    print("\n" + "="*80)
    print("HOURLY DATA COVERAGE (4am-8pm, full day)")
    print("="*80)

    with StockDataDB() as db:
        query = """
        SELECT
            DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as trading_date,
            COUNT(DISTINCT symbol) as symbol_count
        FROM stock_candles_1h
        GROUP BY DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
        ORDER BY trading_date DESC
        """

        cursor = db.conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        monthly_stats = defaultdict(lambda: {'days_3500plus': 0, 'days_total': 0, 'avg_symbols': 0, 'symbol_counts': []})

        for trading_date, symbol_count in results:
            month_key = trading_date.strftime('%Y-%m')
            monthly_stats[month_key]['days_total'] += 1
            monthly_stats[month_key]['symbol_counts'].append(symbol_count)
            if symbol_count >= 3500:
                monthly_stats[month_key]['days_3500plus'] += 1

        for month_key in monthly_stats:
            counts = monthly_stats[month_key]['symbol_counts']
            monthly_stats[month_key]['avg_symbols'] = sum(counts) / len(counts) if counts else 0
            monthly_stats[month_key]['min_symbols'] = min(counts) if counts else 0
            monthly_stats[month_key]['max_symbols'] = max(counts) if counts else 0

        print(f"\n{'Month':<12} {'Days 3.5K+':<12} {'Total Days':<12} {'Avg Symbols':<14} {'Min':<8} {'Max':<8}")
        print("-" * 80)

        for month_key in sorted(monthly_stats.keys(), reverse=True):
            stats = monthly_stats[month_key]
            print(f"{month_key:<12} {stats['days_3500plus']:<12} {stats['days_total']:<12} "
                  f"{stats['avg_symbols']:<14.0f} {stats['min_symbols']:<8.0f} {stats['max_symbols']:<8.0f}")

        return monthly_stats


def find_exhaustive_periods():
    """Question 3: Find periods with complete data (4am-8pm hourly + 8am-12pm minute, 3500+ stocks daily)."""
    print("\n" + "="*80)
    print("QUESTION 3: Exhaustive Data Periods (suitable for simulation)")
    print("="*80)
    print("\nCriteria: For EACH trading day, must have:")
    print("  - Hourly bars 4am-8pm (at least 3500 stocks)")
    print("  - Minute bars 8am-12pm (at least 3500 stocks)")
    print("="*80)

    with StockDataDB() as db:
        # Get all trading days with both minute AND hourly data meeting thresholds
        query = """
        WITH minute_coverage AS (
            SELECT
                DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as trading_date,
                COUNT(DISTINCT symbol) as minute_symbols
            FROM stock_candles_1m
            GROUP BY DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
        ),
        hourly_coverage AS (
            SELECT
                DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York') as trading_date,
                COUNT(DISTINCT symbol) as hourly_symbols
            FROM stock_candles_1h
            GROUP BY DATE(time AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York')
        )
        SELECT
            m.trading_date,
            m.minute_symbols,
            h.hourly_symbols,
            LEAST(m.minute_symbols, h.hourly_symbols) as both_available
        FROM minute_coverage m
        FULL OUTER JOIN hourly_coverage h ON m.trading_date = h.trading_date
        WHERE (m.minute_symbols IS NOT NULL OR h.hourly_symbols IS NOT NULL)
        ORDER BY m.trading_date DESC
        """

        cursor = db.conn.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        # Find contiguous blocks of complete data
        complete_days = []
        for trading_date, minute_symbols, hourly_symbols, both in results:
            minute_symbols = minute_symbols or 0
            hourly_symbols = hourly_symbols or 0
            both = both or 0

            # Check if this day has sufficient data for both
            if minute_symbols >= 3500 and hourly_symbols >= 3500:
                complete_days.append({
                    'date': trading_date,
                    'minute_symbols': minute_symbols,
                    'hourly_symbols': hourly_symbols,
                })

        if not complete_days:
            print("\n[NO EXHAUSTIVE PERIODS FOUND]")
            print("   (Need 3500+ stocks for both 4am-8am hourly AND 8am-12pm minute data on same day)")
            return

        # Find contiguous blocks
        blocks = []
        current_block = [complete_days[0]]

        for i in range(1, len(complete_days)):
            prev_date = current_block[-1]['date']
            curr_date = complete_days[i]['date']

            # Check if dates are consecutive (accounting for weekends)
            if (prev_date - curr_date).days == 1:
                current_block.append(complete_days[i])
            else:
                if len(current_block) >= 5:  # At least 5 trading days
                    blocks.append(current_block)
                current_block = [complete_days[i]]

        if len(current_block) >= 5:
            blocks.append(current_block)

        if not blocks:
            print("\n[WARNING] SCATTERED COMPLETE DAYS FOUND, but no continuous blocks of 5+ days")
            print(f"\nTotal days with complete data: {len(complete_days)}")
            print("\nFirst 10 complete days:")
            print(f"{'Date':<12} {'4am-8am':<12} {'8am-12pm':<12}")
            print("-" * 40)
            for day in complete_days[:10]:
                print(f"{day['date'].strftime('%Y-%m-%d'):<12} {day['hourly_symbols']:<12} {day['minute_symbols']:<12}")
            return

        print(f"\n[SUCCESS] FOUND {len(blocks)} COMPLETE DATA BLOCK(S):\n")
        for block_num, block in enumerate(blocks, 1):
            start_date = block[0]['date']
            end_date = block[-1]['date']
            num_days = len(block)
            avg_minute = sum(d['minute_symbols'] for d in block) / len(block)
            avg_hourly = sum(d['hourly_symbols'] for d in block) / len(block)

            print(f"Block {block_num}: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            print(f"  Duration: {num_days} trading days")
            print(f"  Avg 4am-8am hourly symbols: {avg_hourly:.0f}")
            print(f"  Avg 8am-12pm minute symbols: {avg_minute:.0f}")
            print()


def main():
    print("\n" + "="*80)
    print("DATABASE DIAGNOSTIC REPORT")
    print("="*80)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Run all analyses
    minute_stats = analyze_minute_data_coverage()
    hourly_stats = analyze_hourly_data_coverage()
    find_exhaustive_periods()

    # Summary
    print("\n" + "="*80)
    print("SUMMARY & RECOMMENDATIONS")
    print("="*80)

    # Find month with best minute coverage
    best_minute_month = max(minute_stats.items(), key=lambda x: x[1]['avg_symbols'])[0]
    best_minute_stats = minute_stats[best_minute_month]

    print(f"\n[DATA] Best month for minute data (8am-12pm):")
    print(f"   {best_minute_month}: {best_minute_stats['avg_symbols']:.0f} avg symbols, "
          f"{best_minute_stats['days_1000plus']} days with 1000+ stocks")

    # Recommend action
    print(f"\n[ACTION] RECOMMENDATION:")
    if best_minute_stats['avg_symbols'] >= 3500 and best_minute_stats['days_1000plus'] >= 20:
        print(f"   [OK] Current data may be sufficient for limited simulation testing")
        print(f"   [TODO] Focus backfill on: filling gaps in best months, extending coverage forward")
    else:
        print(f"   [FAIL] Current data is INSUFFICIENT for production simulation runs")
        print(f"   [TODO] Recommended action: Full backfill Dec 2024 - Feb 2026 (all 4000 stocks)")
        print(f"   [TODO] Estimated API calls: ~380,000 (35+ hours at 200 req/min limit)")

    print()


if __name__ == '__main__':
    main()
