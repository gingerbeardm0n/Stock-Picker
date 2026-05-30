#!/usr/bin/env python3
"""
Database coverage audit — high-level overview of what data exists and what's missing.
Run from repo root: python research/maintenance/diagnostics/check_backfill_coverage.py
"""
import sys
import psycopg2
import os
from dotenv import load_dotenv
from datetime import date

# Fix Windows cp1252 encoding issues
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env.paper'))

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:changeme123@localhost:5432/stockdata')

conn = psycopg2.connect(DB_CONN)
cur = conn.cursor()

TODAY = date.today()

print("=" * 65)
print(f"DATABASE COVERAGE AUDIT  (run date: {TODAY})")
print("=" * 65)

# ── 1. Overall date range per table ─────────────────────────────
print("\n── Overall Date Range Per Table ──")
for table in ['stock_candles_1m', 'stock_candles_1h', 'stock_candles_1d']:
    try:
        cur.execute(f"""
            SELECT MIN(time)::date, MAX(time)::date,
                   COUNT(DISTINCT symbol), COUNT(*)
            FROM {table}
        """)
        r = cur.fetchone()
        print(f"\n{table}:")
        print(f"  Earliest : {r[0]}")
        print(f"  Latest   : {r[1]}")
        print(f"  Symbols  : {r[2]:,}")
        print(f"  Total rows: {r[3]:,}")
    except Exception as e:
        print(f"  ERROR: {e}")
        conn.rollback()

# ── 2. Monthly summary — ALL years ──────────────────────────────
print("\n\n── Monthly Row Counts — stock_candles_1m (all time) ──")
print(f"{'Month':<12} {'Symbols':>10} {'Rows':>14}  Note")
print("-" * 55)
try:
    cur.execute("""
        SELECT
            to_char(date_trunc('month', time), 'YYYY-MM') AS month,
            COUNT(DISTINCT symbol) AS symbols,
            COUNT(*) AS rows
        FROM stock_candles_1m
        GROUP BY 1
        ORDER BY 1
    """)
    rows = cur.fetchall()
    prev_symbols = None
    for r in rows:
        note = ""
        if prev_symbols is not None:
            ratio = r[1] / prev_symbols if prev_symbols > 0 else 0
            if ratio < 0.5:
                note = "  ⚠ big drop in symbols"
            elif ratio > 2.0:
                note = "  ⚠ big jump in symbols"
        print(f"{r[0]:<12} {r[1]:>10,} {r[2]:>14,}{note}")
        prev_symbols = r[1]
    if not rows:
        print("  No data found in stock_candles_1m")
except Exception as e:
    print(f"  ERROR: {e}")
    conn.rollback()

# ── 3. Recent gap: last good date → today ───────────────────────
print("\n\n── Recent Gap Analysis (last 30 trading days) ──")
try:
    cur.execute("""
        SELECT DISTINCT time::date AS trading_date, COUNT(DISTINCT symbol) AS symbols
        FROM stock_candles_1m
        WHERE time >= CURRENT_DATE - INTERVAL '45 days'
        GROUP BY 1
        ORDER BY 1 DESC
        LIMIT 30
    """)
    rows = cur.fetchall()
    if rows:
        print(f"{'Date':<14} {'Symbols':>10}")
        print("-" * 28)
        for r in rows:
            print(f"{str(r[0]):<14} {r[1]:>10,}")
        last_date = rows[0][0]
        gap_days = (TODAY - last_date).days
        print(f"\n  Last date with data : {last_date}")
        print(f"  Today               : {TODAY}")
        print(f"  Gap                 : {gap_days} calendar days")
    else:
        print("  No data in last 45 days")
except Exception as e:
    print(f"  ERROR: {e}")
    conn.rollback()

# ── 4. 2023 / 2024 symbol coverage ──────────────────────────────
print("\n\n── 2023 / 2024 Symbol Coverage ──")
try:
    for year in [2023, 2024]:
        cur.execute(f"""
            SELECT COUNT(DISTINCT symbol),
                   MIN(time)::date,
                   MAX(time)::date
            FROM stock_candles_1m
            WHERE time >= '{year}-01-01' AND time < '{year+1}-01-01'
        """)
        r = cur.fetchone()
        if r[0]:
            print(f"  {year}: {r[0]:,} symbols  |  {r[1]} → {r[2]}")
        else:
            print(f"  {year}: no data")
except Exception as e:
    print(f"  ERROR: {e}")
    conn.rollback()

cur.close()
conn.close()
print("\n" + "=" * 65)
