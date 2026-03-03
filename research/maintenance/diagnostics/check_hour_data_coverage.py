#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from utils.query_helpers import StockDataDB
from datetime import datetime

with StockDataDB() as db:
    cursor = db.conn.cursor()

    print("\n=== HOUR BAR DATA COVERAGE (stock_candles_1h) ===\n")

    # Check date range
    cursor.execute("""
        SELECT MIN(time), MAX(time), COUNT(*) as total_candles
        FROM stock_candles_1h;
    """)
    min_time, max_time, total_candles = cursor.fetchone()
    print(f"Date range: {min_time} to {max_time}")
    print(f"Total candles: {total_candles:,}\n")

    # Check symbols per day
    cursor.execute("""
        SELECT
          DATE(time) as date,
          COUNT(DISTINCT symbol) as symbol_count,
          COUNT(*) as total_bars
        FROM stock_candles_1h
        GROUP BY DATE(time)
        ORDER BY date DESC
        LIMIT 20;
    """)

    print(f"{'Date':<12} {'Symbols':<12} {'Total Bars':<15}")
    print("-" * 39)

    rows = cursor.fetchall()
    for date, symbol_count, total_bars in rows:
        print(f"{str(date):<12} {symbol_count:<12} {total_bars:<15,}")

    # Summary stats
    cursor.execute("""
        SELECT
          COUNT(DISTINCT day) as trading_days,
          COUNT(DISTINCT symbol) as total_unique_symbols
        FROM (
          SELECT DATE(time AT TIME ZONE 'UTC') as day, symbol
          FROM stock_candles_1h
        ) daily_data;
    """)

    trading_days, total_symbols = cursor.fetchone()
    print(f"\nSummary:")
    print(f"  Trading days with data: {trading_days}")
    print(f"  Unique symbols total: {total_symbols:,}")

    cursor.close()
