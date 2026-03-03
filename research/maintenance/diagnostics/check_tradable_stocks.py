#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from utils.query_helpers import StockDataDB

with StockDataDB() as db:
    cursor = db.conn.cursor()

    # Check daily symbol counts
    cursor.execute("""
        SELECT
          date,
          COUNT(DISTINCT symbol) as symbol_count
        FROM tradable_stocks_by_date
        GROUP BY date
        ORDER BY date DESC
        LIMIT 15;
    """)

    print("\n=== Daily Symbol Counts in tradable_stocks_by_date ===\n")
    print(f"{'Date':<12} {'Symbol Count':<15}")
    print("-" * 27)

    rows = cursor.fetchall()
    for date, count in rows:
        print(f"{str(date):<12} {count:<15}")

    # Total unique symbols
    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM tradable_stocks_by_date;")
    total_unique = cursor.fetchone()[0]
    print(f"\nTotal unique symbols across all dates: {total_unique:,}")

    # Date range
    cursor.execute("SELECT MIN(date), MAX(date) FROM tradable_stocks_by_date;")
    min_date, max_date = cursor.fetchone()
    print(f"Date range: {min_date} to {max_date}")

    cursor.close()
