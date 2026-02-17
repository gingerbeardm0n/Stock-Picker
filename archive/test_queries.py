#!/usr/bin/env python3
"""
Test Database Queries
Run example queries to verify data collection and see sample data.
"""

import psycopg2
import os
from dotenv import load_dotenv
from datetime import datetime
import pytz

load_dotenv()

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:yourpassword@localhost:5432/stockdata')

def run_query(cursor, title, query, show_results=True):
    """Run a query and display results"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print(f"\nSQL:\n{query}\n")

    try:
        cursor.execute(query)
        results = cursor.fetchall()

        if show_results and results:
            print(f"Results ({len(results)} rows):")
            for row in results[:20]:  # Show first 20 rows
                print(f"  {row}")

            if len(results) > 20:
                print(f"\n  ... and {len(results) - 20} more rows")
        elif not results:
            print("[No results] - This might be OK if no data has been collected yet")

        return results

    except Exception as e:
        print(f"[ERROR] Query failed: {e}")
        return []

def main():
    """Run test queries"""

    print("\n" + "=" * 70)
    print("  DATABASE TEST QUERIES")
    print("=" * 70)
    print(f"\nConnecting to: {DB_CONN.split('@')[1]}")

    conn = psycopg2.connect(DB_CONN)
    cursor = conn.cursor()

    # 1. Check data counts
    run_query(cursor, "1. Data Counts - Minute Bars (9am-12pm)", """
        SELECT
            '1m' AS timeframe,
            COUNT(*) AS candle_count,
            COUNT(DISTINCT symbol) AS unique_symbols,
            MIN(time) AS oldest,
            MAX(time) AS newest
        FROM stock_candles_1m;
    """)

    run_query(cursor, "1b. Data Counts - Hour Bars", """
        SELECT
            '1h' AS timeframe,
            COUNT(*) AS candle_count,
            COUNT(DISTINCT symbol) AS unique_symbols,
            MIN(time) AS oldest,
            MAX(time) AS newest
        FROM stock_candles_1h;
    """)

    run_query(cursor, "1c. Data Counts - Daily Bars", """
        SELECT
            '1d' AS timeframe,
            COUNT(*) AS candle_count,
            COUNT(DISTINCT symbol) AS unique_symbols,
            MIN(time) AS oldest,
            MAX(time) AS newest
        FROM stock_candles_1d;
    """)

    # 2. Sample candle data
    run_query(cursor, "2. Sample Minute Candles (Latest 10)", """
        SELECT
            time AT TIME ZONE 'America/New_York' AS time_et,
            symbol,
            close,
            volume
        FROM stock_candles_1m
        ORDER BY time DESC
        LIMIT 10;
    """)

    # 3. Top volume stocks today
    et = pytz.timezone('America/New_York')
    today = datetime.now(et).date()

    run_query(cursor, "3. Top Volume Stocks (Today 9am-12pm)", f"""
        SELECT
            symbol,
            SUM(volume) AS total_volume,
            ROUND(AVG(close)::numeric, 2) AS avg_price
        FROM stock_candles_1m
        WHERE time >= '{today}'::date
        GROUP BY symbol
        ORDER BY total_volume DESC
        LIMIT 10;
    """)

    # 4. Morning trading (9am-12pm today)
    run_query(cursor, "4. Morning Trading Volume (Today 9am-12pm ET)", f"""
        SELECT
            symbol,
            COUNT(*) AS candle_count,
            SUM(volume) AS morning_volume,
            MIN(low) AS morning_low,
            MAX(high) AS morning_high
        FROM stock_candles_1m
        WHERE time >= '{today}'::date
          AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') BETWEEN 9 AND 11
        GROUP BY symbol
        HAVING SUM(volume) > 10000
        ORDER BY morning_volume DESC
        LIMIT 10;
    """)

    # 5. Stock metadata
    run_query(cursor, "5. Stock Metadata Sample", """
        SELECT symbol, name, exchange, tradable, status
        FROM stock_metadata
        ORDER BY symbol
        LIMIT 10;
    """)

    # 6. Database size
    run_query(cursor, "6. Database Size", """
        SELECT
            pg_size_pretty(pg_database_size('stockdata')) AS total_db_size,
            pg_size_pretty(pg_total_relation_size('stock_candles_1m')) AS minute_bars_size,
            pg_size_pretty(pg_total_relation_size('stock_candles_1h')) AS hour_bars_size,
            pg_size_pretty(pg_total_relation_size('stock_candles_1d')) AS daily_bars_size;
    """)

    # 7. Data freshness
    run_query(cursor, "7. Data Freshness (Latest Timestamps)", """
        SELECT '1m' AS timeframe,
               MAX(time) AT TIME ZONE 'America/New_York' AS latest_data_et,
               NOW() AT TIME ZONE 'America/New_York' - MAX(time) AS age
        FROM stock_candles_1m
        UNION ALL
        SELECT '1h', MAX(time) AT TIME ZONE 'America/New_York', NOW() AT TIME ZONE 'America/New_York' - MAX(time)
        FROM stock_candles_1h
        UNION ALL
        SELECT '1d', MAX(time) AT TIME ZONE 'America/New_York', NOW() AT TIME ZONE 'America/New_York' - MAX(time)
        FROM stock_candles_1d
        ORDER BY timeframe;
    """)

    # 8. Test relative volume function (if data exists)
    run_query(cursor, "8. Test Relative Volume Function (First Symbol)", """
        SELECT
            symbol,
            get_relative_volume(symbol, NOW(), 30) AS relative_volume
        FROM stock_candles_1m
        LIMIT 1;
    """, show_results=True)

    # Summary
    print("\n" + "=" * 70)
    print("  TEST COMPLETE")
    print("=" * 70)
    print("\nNext steps:")
    print("  - If you see data: Great! Your database is working.")
    print("  - If no data: Run 'python database/backfill_historical.py' first")
    print("  - For live updates: Run 'python database/collect_data.py'")
    print()

    cursor.close()
    conn.close()

if __name__ == "__main__":
    try:
        main()
    except psycopg2.OperationalError as e:
        print(f"\n[ERROR] Cannot connect to database: {e}")
        print("\nMake sure:")
        print("  1. Docker container is running: docker ps")
        print("  2. Connection string is correct in .env")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
