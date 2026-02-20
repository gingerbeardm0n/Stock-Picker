#!/usr/bin/env python3
"""
Database Status Report
======================
Shows comprehensive information about what data we have collected.
Helps identify gaps, coverage, and data quality.

Usage:
    python maintenance/db_status.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.query_helpers import StockDataDB
from datetime import datetime, timedelta
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def print_header(title):
    """Print a formatted header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")

def format_number(n):
    """Format large numbers with commas"""
    return f"{n:,}"

def get_db_status():
    """Get comprehensive database status"""

    with StockDataDB() as db:
        # Get table sizes
        conn = db.conn
        cursor = conn.cursor()

        print_header("DATABASE STATUS REPORT")
        print(f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # ===== TABLE SIZES =====
        print_header("1. TABLE SIZES")

        tables = {
            'stock_candles_1m': 'Minute bars (1-min candles)',
            'stock_candles_1h': 'Hour bars (1-hour candles)',
            'stock_candles_1d': 'Daily bars (daily candles)',
            'stock_fundamentals': 'Fundamentals (float, market cap)'
        }

        total_records = 0
        for table, description in tables.items():
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            total_records += count
            print(f"  {table:<25} {format_number(count):>15} rows  ({description})")

        print(f"  {'TOTAL':<25} {format_number(total_records):>15} rows\n")

        # ===== DATE RANGE =====
        print_header("2. DATA DATE RANGE")

        for table in ['stock_candles_1m', 'stock_candles_1h', 'stock_candles_1d']:
            cursor.execute(f"SELECT MIN(time), MAX(time) FROM {table}")
            result = cursor.fetchone()
            if result and result[0]:
                min_date = result[0]
                max_date = result[1]
                cursor.execute(f"SELECT COUNT(DISTINCT DATE(time)) FROM {table}")
                distinct_days = cursor.fetchone()[0]
                print(f"  {table}:")
                print(f"    Earliest: {min_date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    Latest:   {max_date.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"    Span:     {(max_date - min_date).days} days ({distinct_days} unique trading days)\n")

        # ===== SYMBOL COVERAGE =====
        print_header("3. SYMBOL COVERAGE")

        for table in ['stock_candles_1m', 'stock_candles_1h', 'stock_candles_1d']:
            cursor.execute(f"SELECT COUNT(DISTINCT symbol) FROM {table}")
            unique_symbols = cursor.fetchone()[0]
            print(f"  {table:<25} {format_number(unique_symbols):>6} unique symbols")

        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM stock_fundamentals")
        fund_symbols = cursor.fetchone()[0]
        print(f"  {'stock_fundamentals':<25} {format_number(fund_symbols):>6} unique symbols (float/mkt cap cached)\n")

        # ===== EARLIEST DATE DETAIL =====
        print_header("4. EARLIEST DATA DETAILS")

        cursor.execute("""
            SELECT DATE(time) as date, COUNT(*) as count, COUNT(DISTINCT symbol) as symbols
            FROM stock_candles_1m
            GROUP BY DATE(time)
            ORDER BY date ASC
            LIMIT 5
        """)
        results = cursor.fetchall()

        if results:
            earliest_date = results[0][0]
            print(f"  First trading day with minute data: {earliest_date.strftime('%Y-%m-%d (%A)')}\n")
            print(f"  {'Date':<12} {'Minute Bars':<15} {'Unique Symbols':<20}")
            print(f"  {'-'*50}")
            for date, count, symbols in results:
                print(f"  {date.strftime('%Y-%m-%d'):<12} {format_number(count):<15} {format_number(symbols):<20}")
            print()

        # ===== MINUTE BAR TIME-OF-DAY COVERAGE =====
        print_header("5. MINUTE BAR TIME-OF-DAY COVERAGE (Most Recent Trading Day)")

        cursor.execute("""
            SELECT DATE(time) FROM stock_candles_1m
            ORDER BY DATE(time) DESC
            LIMIT 1
        """)
        recent_date_result = cursor.fetchone()

        if recent_date_result:
            recent_date = recent_date_result[0]

            # Get bars by hour for that day
            cursor.execute(f"""
                SELECT EXTRACT(HOUR FROM time) as hour, COUNT(*) as count, COUNT(DISTINCT symbol) as symbols
                FROM stock_candles_1m
                WHERE DATE(time) = %s
                GROUP BY EXTRACT(HOUR FROM time)
                ORDER BY hour ASC
            """, (recent_date,))

            hour_data = cursor.fetchall()
            print(f"  Date: {recent_date.strftime('%Y-%m-%d (%A)')}\n")
            print(f"  {'Time':<10} {'Bars':<15} {'Symbols':<15}")
            print(f"  {'-'*40}")

            for hour, count, symbols in hour_data:
                time_str = f"{int(hour):02d}:00"
                print(f"  {time_str:<10} {format_number(count):<15} {format_number(symbols):<15}")

            # Check if we have 4am bars
            cursor.execute(f"""
                SELECT COUNT(*) FROM stock_candles_1m
                WHERE DATE(time) = %s AND EXTRACT(HOUR FROM time) = 4
            """, (recent_date,))
            count_4am = cursor.fetchone()[0]

            print(f"\n  [OK] 4 AM bars available: {'YES' if count_4am > 0 else 'NO'}")
            print()

        # ===== DATA COMPLETENESS =====
        print_header("6. DATA COMPLETENESS ANALYSIS")

        # For the earliest date, check how complete the data is
        cursor.execute("""
            SELECT DATE(time) FROM stock_candles_1m
            ORDER BY DATE(time) ASC
            LIMIT 1
        """)
        earliest_result = cursor.fetchone()

        if earliest_result:
            earliest = earliest_result[0]

            # Expected: 4am-12pm = 8 hours = 480 minutes per symbol per day
            expected_bars_per_symbol = 480

            cursor.execute(f"""
                SELECT symbol, COUNT(*) as count
                FROM stock_candles_1m
                WHERE DATE(time) = %s
                GROUP BY symbol
                ORDER BY count DESC
                LIMIT 10
            """, (earliest,))

            completeness = cursor.fetchall()

            print(f"  For date: {earliest.strftime('%Y-%m-%d (%A)')}")
            print(f"  (Expected: {expected_bars_per_symbol} bars/symbol for 4am-12pm window)\n")
            print(f"  {'Symbol':<10} {'Bars':<10} {'% Complete':<15}")
            print(f"  {'-'*40}")

            total_complete = 0
            for symbol, count in completeness:
                pct = (count / expected_bars_per_symbol) * 100
                status = "[OK]" if pct > 90 else "[~]" if pct > 50 else "[XX]"
                print(f"  {status} {symbol:<8} {count:<10} {pct:.1f}%")
                total_complete += 1

            print()

        # ===== AVERAGE BARS PER SYMBOL PER DATE =====
        print_header("7. AVERAGE BARS PER SYMBOL PER DATE")

        cursor.execute("""
            SELECT
                DATE(time),
                COUNT(*) as total_bars,
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(*) / COUNT(DISTINCT symbol) as avg_bars_per_symbol
            FROM stock_candles_1m
            GROUP BY DATE(time)
            ORDER BY DATE(time) DESC
            LIMIT 10
        """)

        avg_data = cursor.fetchall()
        print(f"  {'Date':<12} {'Total Bars':<15} {'Symbols':<12} {'Avg/Symbol':<15}")
        print(f"  {'-'*55}")

        for date, total, symbols, avg in avg_data:
            print(f"  {date.strftime('%Y-%m-%d'):<12} {format_number(total):<15} {format_number(symbols):<12} {avg:<15.1f}")

        print()

        # ===== HOURLY AND DAILY BAR STATUS =====
        print_header("8. HOURLY & DAILY BAR COVERAGE")

        # Hour bars
        cursor.execute("""
            SELECT
                COUNT(*) as total_bars,
                COUNT(DISTINCT symbol) as unique_symbols,
                COUNT(DISTINCT DATE(time)) as unique_days
            FROM stock_candles_1h
        """)

        hour_stats = cursor.fetchone()
        print(f"  Hour bars (1h candles):")
        print(f"    Total: {format_number(hour_stats[0])} bars")
        print(f"    Symbols: {format_number(hour_stats[1])} unique")
        print(f"    Trading days: {format_number(hour_stats[2])} days\n")

        # Daily bars
        cursor.execute("""
            SELECT
                COUNT(*) as total_bars,
                COUNT(DISTINCT symbol) as unique_symbols,
                MIN(time) as earliest,
                MAX(time) as latest
            FROM stock_candles_1d
        """)

        daily_stats = cursor.fetchone()
        print(f"  Daily bars (1d candles):")
        print(f"    Total: {format_number(daily_stats[0])} bars")
        print(f"    Symbols: {format_number(daily_stats[1])} unique")
        if daily_stats[2]:
            print(f"    Date range: {daily_stats[2].strftime('%Y-%m-%d')} to {daily_stats[3].strftime('%Y-%m-%d')}\n")

        # ===== RECOMMENDATIONS =====
        print_header("9. RECOMMENDATIONS")

        print(f"  [+] Minute bars: Good for detailed 9am-12pm analysis")
        print(f"  [+] Hourly bars: Can use 4am-7am for premarket overview (low volume)")
        print(f"  [+] Daily bars: Use for 20-day average volume baseline\n")

        print(f"  SUGGESTED STRATEGY:")
        print(f"  1. Use MINUTE bars 7am-12pm for precise entry/exit timing")
        print(f"  2. Use HOURLY bars 4am-7am to capture premarket move early")
        print(f"  3. Use DAILY bars for relative volume baseline calculations\n")

        print(f"  NEXT STEPS:")
        print(f"  1. Run 60-day backfill: python database/backfill_optimized.py")
        print(f"  2. Verify 4am-12pm coverage across all dates")
        print(f"  3. Run sanity check on expanded dataset")
        print(f"  4. Update scanner to use hourly bars 4am-7am + minute bars 7am-12pm\n")

        cursor.close()

if __name__ == '__main__':
    get_db_status()
