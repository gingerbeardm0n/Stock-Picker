#!/usr/bin/env python3
"""
Timezone Verification Script
=============================
Checks if our minute bar timestamps are correct for 4am-12pm EST window.

Expected window:
  4:00 AM EST = 9:00 AM UTC
  12:00 PM EST = 5:00 PM UTC (17:00 UTC)

So we should see timestamps from 09:00-17:00 UTC.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils.query_helpers import StockDataDB
from datetime import datetime
import pytz

def check_timezone():
    """Check if minute bars are in correct timezone"""

    with StockDataDB() as db:
        conn = db.conn
        cursor = conn.cursor()

        print("\n" + "="*80)
        print("  TIMEZONE VERIFICATION")
        print("="*80 + "\n")

        print("Expected window for 4am-12pm EST:")
        print("  4:00 AM EST = 09:00 UTC")
        print("  12:00 PM EST = 17:00 UTC")
        print("\nSo we should see timestamps from 09:00-17:00 UTC\n")

        # Get a sample of timestamps from a recent trading day
        cursor.execute("""
            SELECT DATE(time) FROM stock_candles_1m
            ORDER BY DATE(time) DESC
            LIMIT 1
        """)

        recent_date = cursor.fetchone()
        if not recent_date:
            print("[ERROR] No minute data found")
            return

        date = recent_date[0]
        print(f"Checking date: {date.strftime('%Y-%m-%d')}\n")

        # Get all unique hours and their bar counts
        print("Current data distribution by UTC hour:")
        print("  UTC Hour  |  Bars  | Symbols | Notes")
        print("  " + "-"*60)

        cursor.execute(f"""
            SELECT
                EXTRACT(HOUR FROM time)::int as hour,
                COUNT(*) as bars,
                COUNT(DISTINCT symbol) as symbols
            FROM stock_candles_1m
            WHERE DATE(time) = %s
            GROUP BY EXTRACT(HOUR FROM time)
            ORDER BY hour ASC
        """, (date,))

        hours_data = cursor.fetchall()
        expected_hours = set(range(9, 18))  # 09:00 to 17:59 UTC
        actual_hours = set()

        for hour, bars, symbols in hours_data:
            hour = int(hour)
            actual_hours.add(hour)

            # Convert UTC hour to EST for reference
            utc_dt = datetime.utcnow().replace(hour=hour, minute=0)
            est_tz = pytz.timezone('US/Eastern')
            est_dt = pytz.utc.localize(utc_dt).astimezone(est_tz)
            est_hour = est_dt.strftime('%H:%M')

            in_window = "[OK]" if hour >= 9 and hour <= 17 else "[XX]"
            print(f"  {hour:02d}:00    | {bars:6,} | {symbols:7,} | EST {est_hour} {in_window}")

        print("\n" + "-"*60)

        # Check if we have the expected window
        missing_hours = expected_hours - actual_hours
        unexpected_hours = actual_hours - expected_hours

        print(f"\nAnalysis:")
        if not missing_hours and not unexpected_hours:
            print("  [OK] PERFECT: Have all expected hours (09:00-17:00 UTC)")
        else:
            if missing_hours:
                print(f"  [XX] MISSING hours (UTC): {sorted(missing_hours)}")
            if unexpected_hours:
                print(f"  [XX] UNEXPECTED hours (UTC): {sorted(unexpected_hours)}")

        # Sample a few raw timestamps to verify
        print(f"\n\nSample raw timestamps from database:")
        print("  (This shows exactly what's stored in the database)\n")

        cursor.execute(f"""
            SELECT
                symbol,
                time,
                volume,
                close
            FROM stock_candles_1m
            WHERE DATE(time) = %s
            ORDER BY time ASC
            LIMIT 5
        """, (date,))

        samples = cursor.fetchall()
        print(f"  {'Symbol':<8} {'Timestamp (Raw)':<30} {'Volume':<12} {'Close':<8}")
        print(f"  {'-'*70}")

        for symbol, time, volume, close in samples:
            time_str = time.strftime('%Y-%m-%d %H:%M:%S %Z') if hasattr(time, 'strftime') else str(time)
            print(f"  {symbol:<8} {time_str:<30} {volume:>12,} {close:>7.2f}")

        # Get the timezone of the database timestamps
        cursor.execute(f"""
            SELECT time::text FROM stock_candles_1m
            WHERE DATE(time) = %s
            LIMIT 1
        """, (date,))

        raw_timestamp = cursor.fetchone()[0]
        print(f"\n\nRaw timestamp from database: {raw_timestamp}")
        print("  (If it has +00:00 or Z at end, it's UTC)")
        print("  (If it has no timezone info, check how it was stored)")

        # Recommendations
        print(f"\n\n{'='*80}")
        print("  RECOMMENDATIONS")
        print(f"{'='*80}\n")

        if actual_hours == expected_hours or (actual_hours >= {9, 10, 11, 12, 13, 14, 15, 16, 17}):
            print("  [OK] Timezone appears CORRECT")
            print("    - We have the expected 09:00-17:00 UTC window")
            print("    - This corresponds to 4am-12pm EST")
            print("    - Safe to proceed with 60-day backfill\n")
        else:
            print("  [XX] Timezone might be INCORRECT")
            print("    - We're not getting the expected window")
            print("    - Need to investigate backfill_optimized.py\n")

        if not missing_hours:
            print("  Next: Run 60-day backfill with confidence")
        else:
            print(f"  Problem: Missing UTC hours {sorted(missing_hours)}")
            print("  These correspond to EST hours:")
            for h in sorted(missing_hours):
                utc_dt = datetime.utcnow().replace(hour=h, minute=0)
                est_tz = pytz.timezone('US/Eastern')
                est_dt = pytz.utc.localize(utc_dt).astimezone(est_tz)
                print(f"    {h:02d}:00 UTC = {est_dt.strftime('%I:%M %p')} EST")

        cursor.close()

if __name__ == '__main__':
    check_timezone()
