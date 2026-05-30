#!/usr/bin/env python3
"""
Scan all 2026 trading days and find stocks meeting RELAXED gapper criteria.
Goal: count unique symbols to decide if Polygon free tier is workable.

Uses stock_candles_1d only (1M rows vs 100M for 1m table) — much faster.
  - Open price = market open (~9:30am proxy)
  - Relative volume = today's total volume / 20-day avg daily volume

Relaxed criteria:
  - Price $1–$30  (live: $2–$20)
  - Up 5%+ from prior close  (live: 10%+)
  - Volume 2x+ avg daily volume  (live: 5x+ at-time rel vol)

Run from repo root:
  python research/maintenance/diagnostics/scan_2026_gappers.py
"""
import psycopg2
import os
from dotenv import load_dotenv
from collections import Counter, defaultdict

load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env.paper'))

DB_CONN = os.getenv('TIMESCALE_CONNECTION_STRING',
                    'postgresql://postgres:changeme123@localhost:5432/stockdata')

conn = psycopg2.connect(DB_CONN)
cur = conn.cursor()

print("=" * 65)
print("2026 GAPPER SCAN  (relaxed: 5%+ open, 2x+ vol — daily bars only)")
print("=" * 65)
print("Running query...", flush=True)

query = """
WITH

-- All daily bars from Dec 2024 onward (need lookback for avg vol)
daily AS (
    SELECT
        symbol,
        time::date        AS trade_date,
        open,
        close,
        volume
    FROM stock_candles_1d
    WHERE time::date >= '2024-12-01'
      AND time::date <= '2026-03-06'
),

-- For each 2026 bar: prior close + 20-day avg volume via window functions
enriched AS (
    SELECT
        symbol,
        trade_date,
        open,
        volume,
        LAG(close)  OVER (PARTITION BY symbol ORDER BY trade_date)  AS prior_close,
        AVG(volume) OVER (
            PARTITION BY symbol
            ORDER BY trade_date
            ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
        )                                                             AS avg_vol_20d
    FROM daily
)

SELECT
    trade_date,
    symbol,
    ROUND(open::numeric, 2)                                             AS open_price,
    ROUND(((open - prior_close) / prior_close * 100)::numeric, 1)      AS pct_chg,
    volume,
    ROUND(avg_vol_20d::numeric, 0)                                      AS avg_vol,
    ROUND((volume / NULLIF(avg_vol_20d, 0))::numeric, 1)               AS vol_ratio
FROM enriched
WHERE trade_date >= '2026-01-01'
  AND prior_close  > 0
  AND open         BETWEEN 1.0 AND 30.0
  AND (open - prior_close) / prior_close  >= 0.05
  AND volume / NULLIF(avg_vol_20d, 0)     >= 2.0
ORDER BY trade_date, vol_ratio DESC
"""

cur.execute(query)
rows = cur.fetchall()

if not rows:
    print("No results — check stock_candles_1d coverage for 2026.")
    cur.close()
    conn.close()
    exit()

# ── Aggregate ────────────────────────────────────────────────────
unique_symbols = set()
by_date = defaultdict(list)
symbol_counts = Counter()

for trade_date, symbol, open_price, pct_chg, volume, avg_vol, vol_ratio in rows:
    unique_symbols.add(symbol)
    by_date[trade_date].append((symbol, pct_chg, vol_ratio))
    symbol_counts[symbol] += 1

trading_days = sorted(by_date.keys())

print(f"\n── Summary ──")
print(f"  Trading days in DB (2026) : {len(trading_days)}")
print(f"  Total qualifying hits     : {len(rows)}")
print(f"  Avg gappers per day       : {len(rows)/len(trading_days):.1f}")
print(f"  UNIQUE SYMBOLS            : {len(unique_symbols)}")

# ── Per-day breakdown ────────────────────────────────────────────
print(f"\n── Per-Day Breakdown ──")
print(f"{'Date':<14} {'Gappers':>8}  Top symbols")
print("-" * 65)
for d in trading_days:
    stocks = by_date[d]
    top = ", ".join(f"{s[0]}({s[2]}x)" for s in stocks[:5])
    print(f"{str(d):<14} {len(stocks):>8}  {top}")

# ── Polygon free tier math ───────────────────────────────────────
GAP_DAYS = 7   # Mar 7-15, 2026 (~7 trading days)
CALLS_PER_MIN_FREE = 5
# 1 Polygon call = 1 symbol's full date range (no need to call per day)
total_calls = len(unique_symbols)
minutes = total_calls / CALLS_PER_MIN_FREE
hours   = minutes / 60

print(f"\n── Polygon Free Tier Feasibility ──")
print(f"  Symbols to backfill  : {len(unique_symbols):,}")
print(f"  Calls needed         : {len(unique_symbols):,}  (1 call per symbol covers full range)")
print(f"  At 5 calls/min       : {minutes:.0f} min  (~{hours:.1f} hrs)")
verdict = "✅ WORKABLE" if hours < 3 else ("⚠️  SLOW BUT POSSIBLE" if hours < 8 else "❌ TOO SLOW — consider $29/mo")
print(f"  Verdict              : {verdict}")

# ── Most frequent gappers ────────────────────────────────────────
print(f"\n── Top 20 Most Frequent Gappers (most days appeared) ──")
print(f"{'Symbol':<10} {'Days':>5}")
print("-" * 20)
for sym, cnt in symbol_counts.most_common(20):
    print(f"{sym:<10} {cnt:>5}")

cur.close()
conn.close()
print("\n" + "=" * 65)
