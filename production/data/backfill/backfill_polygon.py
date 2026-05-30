#!/usr/bin/env python3
"""
Polygon Free Tier Backfill
Fills the Mar 7-15 2026 data gap for the 941 gapper symbols identified in the DB.

Two phases:
  Phase 1: Daily bars for ALL symbols via grouped endpoint  (5 calls,   ~1 min)
  Phase 2: Minute bars (4am-12pm ET) for gapper symbols     (941 calls, ~3.1 hrs)
           - 8am-12pm minutes → stock_candles_1m directly
           - 4am-8am minutes  → aggregated to hourly → stock_candles_1h

Setup (do this before running):
  1. Sign up free at https://massive.com  (formerly polygon.io)
  2. Copy your API key from the dashboard
  3. Add to .env.paper:  POLYGON_API_KEY=your_key_here

Run from repo root:
  python production/data/backfill/backfill_polygon.py
"""
import os
import sys
import json

# Fix Windows cp1252 encoding issues with Unicode output
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from collections import defaultdict
from datetime import datetime
from dotenv import load_dotenv
import pytz

# ── Helpers ───────────────────────────────────────────────────────
def _fmt_eta(seconds):
    """Format seconds into h:mm or m:ss string."""
    if seconds >= 3600:
        return f'{int(seconds//3600)}h {int((seconds%3600)//60)}m'
    return f'{int(seconds//60)}m {int(seconds%60)}s'

# ── Path setup ────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env.paper'))

# ── Config ────────────────────────────────────────────────────────
POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', '')
DB_CONN         = os.getenv('TIMESCALE_CONNECTION_STRING',
                             'postgresql://postgres:changeme123@localhost:5432/stockdata')

ET              = pytz.timezone('America/New_York')
UTC             = pytz.UTC
POLYGON_BASE    = 'https://api.polygon.io'
PROGRESS_FILE   = os.path.join(os.path.dirname(__file__), 'backfill_polygon_progress.json')

# Trading days to fill (Mar 9-13 2026, the gap between Mar 6 last-good and Mar 15 today)
GAP_TRADING_DAYS = ['2026-03-09', '2026-03-10', '2026-03-11', '2026-03-12', '2026-03-13']
FROM_DATE        = '2026-03-07'
TO_DATE          = '2026-03-15'

# Free tier: 5 calls/min → 12 sec between calls
SLEEP_BETWEEN_CALLS = 12
SLEEP_ON_429        = 65   # wait >60s to reset the rate limit window


# ============================================================
# Progress file — enables resume after crash or Ctrl+C
# ============================================================

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {
        'phase1_daily_dates_done': [],
        'phase2_symbols_done': [],
        'total_inserted_1d': 0,
        'total_inserted_1m': 0,
        'total_inserted_1h': 0,
    }


def save_progress(p):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(p, f, indent=2)


# ============================================================
# Polygon REST helpers
# ============================================================

def polygon_get(url, params=None):
    """GET a Polygon endpoint. Handles 429 with backoff. Returns JSON dict or None."""
    p = dict(params or {})
    p['apiKey'] = POLYGON_API_KEY
    for attempt in range(3):
        try:
            resp = requests.get(url, params=p, timeout=30)
            if resp.status_code == 429:
                print(f'  [429] Rate limited — waiting {SLEEP_ON_429}s...', flush=True)
                time.sleep(SLEEP_ON_429)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            print(f'  [ERROR] {e}')
            if attempt < 2:
                time.sleep(5)
    return None


def ms_to_utc(ms):
    """Convert Polygon millisecond epoch timestamp to UTC-aware datetime."""
    return datetime.utcfromtimestamp(ms / 1000).replace(tzinfo=UTC)


# ============================================================
# Database helpers
# ============================================================

def get_db_conn():
    return psycopg2.connect(DB_CONN)


def flush_to_db(conn, table, rows):
    """
    Batch-insert rows into table using the same ON CONFLICT DO NOTHING pattern
    as backfill_optimized.py. Returns count of newly inserted rows.
    """
    if not rows:
        return 0
    sql = f"""
        INSERT INTO {table} (time, symbol, open, high, low, close, volume, trade_count, vwap)
        VALUES %s
        ON CONFLICT (time, symbol) DO NOTHING
    """
    cur = conn.cursor()
    execute_values(cur, sql, rows, page_size=10_000)
    inserted = cur.rowcount
    conn.commit()
    cur.close()
    return max(inserted, 0)


def aggregate_minutes_to_hours(minute_bars, symbol):
    """
    Group minute bars into hourly OHLCV rows for DB insert.
    minute_bars: list of dicts with ts_utc, o, h, l, c, v, n, vw
    Returns: list of tuples ready for flush_to_db into stock_candles_1h
    """
    buckets = defaultdict(list)
    for bar in minute_bars:
        ts_et = bar['ts_utc'].astimezone(ET)
        hour_key = ts_et.replace(minute=0, second=0, microsecond=0)
        buckets[hour_key].append(bar)

    rows = []
    for hour_ts in sorted(buckets):
        bars = buckets[hour_ts]
        total_vol = sum(b['v'] for b in bars)
        total_tc = sum(b['n'] or 0 for b in bars)
        # Volume-weighted VWAP approximation
        vwap_num = sum((b['vw'] or 0) * b['v'] for b in bars if b['vw'])
        vwap = vwap_num / total_vol if total_vol > 0 and vwap_num > 0 else None
        rows.append((
            hour_ts.astimezone(UTC),
            symbol,
            bars[0]['o'],                       # open = first bar's open
            max(b['h'] for b in bars),          # high
            min(b['l'] for b in bars),          # low
            bars[-1]['c'],                       # close = last bar's close
            total_vol,
            total_tc if total_tc > 0 else None,
            vwap,
        ))
    return rows


# ============================================================
# Symbol list — queried from DB (same logic as scan_2026_gappers.py)
# ============================================================

def get_gapper_symbols(conn):
    """
    Return the ~941 unique gapper symbols that appeared in 2026:
    up 5%+ at open, 2x+ daily volume, price $1-$30.
    """
    query = """
        WITH
        daily AS (
            SELECT symbol, time::date AS trade_date, open, close, volume
            FROM stock_candles_1d
            WHERE time::date >= '2024-12-01' AND time::date <= '2026-03-06'
        ),
        enriched AS (
            SELECT symbol, trade_date, open, volume,
                LAG(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS prior_close,
                AVG(volume) OVER (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 21 PRECEDING AND 1 PRECEDING
                ) AS avg_vol_20d
            FROM daily
        )
        SELECT DISTINCT symbol
        FROM enriched
        WHERE trade_date >= '2026-01-01'
          AND prior_close > 0
          AND open BETWEEN 1.0 AND 30.0
          AND (open - prior_close) / prior_close >= 0.05
          AND volume / NULLIF(avg_vol_20d, 0) >= 2.0
        ORDER BY symbol
    """
    cur = conn.cursor()
    cur.execute(query)
    symbols = [r[0] for r in cur.fetchall()]
    cur.close()
    print(f'Gapper universe: {len(symbols)} symbols')
    if len(symbols) < 100:
        print('[WARN] Unexpectedly few symbols — check DB coverage for 2026')
    return symbols


# ============================================================
# Phase 1: Grouped daily bars (ALL symbols, 1 call per trading day)
# ============================================================

def phase1_daily(conn, progress):
    print('\n' + '=' * 65)
    print('PHASE 1  Daily bars via grouped endpoint  (5 API calls)')
    print('=' * 65)

    total = 0
    for date_str in GAP_TRADING_DAYS:
        if date_str in progress['phase1_daily_dates_done']:
            print(f'  {date_str}: already done')
            continue

        print(f'  {date_str} ...', end=' ', flush=True)
        url  = f'{POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/{date_str}'
        data = polygon_get(url, {'adjusted': 'true'})

        if not data or not data.get('results'):
            print('no results')
        else:
            bars = data['results']
            rows = []
            for bar in bars:
                rows.append((
                    ms_to_utc(bar['t']),
                    bar['T'],           # ticker symbol
                    bar['o'],
                    bar['h'],
                    bar['l'],
                    bar['c'],
                    int(bar['v']),
                    bar.get('n'),       # trade_count — nullable
                    bar.get('vw'),      # vwap — nullable
                ))
            inserted = flush_to_db(conn, 'stock_candles_1d', rows)
            total                        += inserted
            progress['total_inserted_1d'] += inserted
            print(f'{len(bars):,} symbols fetched, {inserted:,} inserted')

        progress['phase1_daily_dates_done'].append(date_str)
        save_progress(progress)
        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f'\nPhase 1 done: {total:,} daily bars inserted')


# ============================================================
# Phase 2: Minute bars 4am-12pm ET — split into 1m + aggregated 1h
# ============================================================

def phase2_intraday(conn, symbols, progress):
    done_set  = set(progress['phase2_symbols_done'])
    remaining = [s for s in symbols if s not in done_set]

    print('\n' + '=' * 65)
    print(f'PHASE 2  Minute bars (4am-12pm ET) -> 1m + aggregated 1h')
    print(f'         {len(symbols)} symbols total')
    print(f'         {len(done_set)} already done  |  {len(remaining)} remaining')
    eta_hrs = len(remaining) * SLEEP_BETWEEN_CALLS / 3600
    print(f'         ETA at {SLEEP_BETWEEN_CALLS}s/call: ~{eta_hrs:.1f} hrs')
    print('=' * 65)

    total_1m    = 0
    total_1h    = 0
    phase_start = time.time()
    SUMMARY_EVERY = 25

    for i, symbol in enumerate(remaining, 1):
        print(f'  [{i}/{len(remaining)}] {symbol} ...', end=' ', flush=True)

        url  = f'{POLYGON_BASE}/v2/aggs/ticker/{symbol}/range/1/minute/{FROM_DATE}/{TO_DATE}'
        data = polygon_get(url, {'adjusted': 'true', 'sort': 'asc', 'limit': '50000'})

        if not data or not data.get('results'):
            print('no results')
        else:
            minute_rows = []    # 8am-12pm → stock_candles_1m
            premarket_bars = [] # 4am-8am  → aggregate to hourly

            for bar in data['results']:
                ts_utc = ms_to_utc(bar['t'])
                ts_et  = ts_utc.astimezone(ET)
                hour   = ts_et.hour

                if 8 <= hour < 12:
                    minute_rows.append((
                        ts_utc, symbol,
                        bar['o'], bar['h'], bar['l'], bar['c'],
                        int(bar['v']), bar.get('n'), bar.get('vw'),
                    ))
                elif 4 <= hour < 8:
                    premarket_bars.append({
                        'ts_utc': ts_utc,
                        'o': bar['o'], 'h': bar['h'], 'l': bar['l'], 'c': bar['c'],
                        'v': int(bar['v']), 'n': bar.get('n'), 'vw': bar.get('vw'),
                    })

            # Insert minute bars
            ins_1m = flush_to_db(conn, 'stock_candles_1m', minute_rows)
            total_1m += ins_1m
            progress['total_inserted_1m'] += ins_1m

            # Aggregate premarket minutes → hourly bars, insert
            hourly_rows = aggregate_minutes_to_hours(premarket_bars, symbol)
            ins_1h = flush_to_db(conn, 'stock_candles_1h', hourly_rows)
            total_1h += ins_1h
            progress['total_inserted_1h'] += ins_1h

            total_bars = len(data['results'])
            print(f'{total_bars} bars -> {ins_1m} 1m + {ins_1h} 1h inserted')

        progress['phase2_symbols_done'].append(symbol)
        save_progress(progress)

        # Progress summary every N symbols
        if i % SUMMARY_EVERY == 0 or i == len(remaining):
            elapsed  = time.time() - phase_start
            rate     = i / elapsed if elapsed > 0 else 0
            eta_secs = (len(remaining) - i) / rate if rate > 0 else 0
            pct      = i / len(remaining) * 100
            print(f'\n  --- Progress: {i}/{len(remaining)} ({pct:.0f}%)  |  '
                  f'1m: {total_1m:,}  1h: {total_1h:,}  |  '
                  f'elapsed {_fmt_eta(elapsed)}  |  '
                  f'ETA {_fmt_eta(eta_secs)} ---\n')

        time.sleep(SLEEP_BETWEEN_CALLS)

    print(f'\nPhase 2 done: {total_1m:,} minute bars + {total_1h:,} hourly bars inserted')


# ============================================================
# Preflight test — validates API key + DB before any real work
# ============================================================

def run_preflight_test(conn):
    """
    Quick smoke-test before committing to a multi-hour run.
    Tests: API key validity, grouped endpoint, per-ticker endpoint, DB insert round-trip.
    Exits with a clear error message if anything fails.
    """
    print('\n--- Preflight Test ---')
    TEST_SYMBOL = 'AAPL'
    TEST_DATE   = '2026-03-13'   # last trading day in our gap

    # 1. API key + grouped endpoint (Phase 1 style)
    print(f'  [1/3] Grouped daily endpoint for {TEST_DATE} ...', end=' ', flush=True)
    url  = f'{POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/{TEST_DATE}'
    data = polygon_get(url, {'adjusted': 'true'})
    if not data:
        print('FAIL - no response (check internet connection)')
        sys.exit(1)
    if data.get('status') == 'ERROR' or data.get('error'):
        print(f'FAIL - {data.get("error", data.get("status"))}')
        sys.exit(1)
    count = data.get('resultsCount', 0)
    if count == 0:
        print(f'FAIL - 0 results returned (API key may be invalid)')
        sys.exit(1)
    print(f'OK  ({count:,} symbols returned)')

    time.sleep(SLEEP_BETWEEN_CALLS)

    # 2. Per-ticker endpoint (Phase 2 style)
    print(f'  [2/3] Per-ticker minute endpoint for {TEST_SYMBOL} ...', end=' ', flush=True)
    url  = f'{POLYGON_BASE}/v2/aggs/ticker/{TEST_SYMBOL}/range/1/minute/{FROM_DATE}/{TO_DATE}'
    data = polygon_get(url, {'adjusted': 'true', 'sort': 'asc', 'limit': '50000'})
    if not data:
        print('FAIL - no response')
        sys.exit(1)
    if data.get('status') == 'ERROR' or data.get('error'):
        print(f'FAIL - {data.get("error", data.get("status"))}')
        sys.exit(1)
    bars = data.get('results', [])
    if not bars:
        print(f'FAIL - 0 bars for {TEST_SYMBOL} (unexpected for a major stock)')
        sys.exit(1)
    # Spot-check: first bar should be within our date range
    first_ts = ms_to_utc(bars[0]['t']).astimezone(ET)
    print(f'OK  ({len(bars)} bars, first: {first_ts.strftime("%Y-%m-%d %H:%M ET")})')

    time.sleep(SLEEP_BETWEEN_CALLS)

    # 3. DB round-trip: insert one test row, verify it lands, delete it
    print(f'  [3/3] DB insert round-trip ...', end=' ', flush=True)
    test_ts = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)   # obviously fake timestamp
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO stock_candles_1d (time, symbol, open, high, low, close, volume)
            VALUES (%s, %s, 1.0, 1.0, 1.0, 1.0, 0)
            ON CONFLICT (time, symbol) DO NOTHING
        """, (test_ts, '__TEST__'))
        conn.commit()
        cur.execute("SELECT 1 FROM stock_candles_1d WHERE symbol = '__TEST__' AND time = %s", (test_ts,))
        if not cur.fetchone():
            print('FAIL - row was not found after insert')
            sys.exit(1)
        cur.execute("DELETE FROM stock_candles_1d WHERE symbol = '__TEST__'")
        conn.commit()
        print('OK')
    except Exception as e:
        print(f'FAIL - {e}')
        sys.exit(1)
    finally:
        cur.close()

    print('\nAll preflight checks passed. Starting backfill...\n')


# ============================================================
# Main
# ============================================================

def main():
    if not POLYGON_API_KEY:
        print('ERROR: POLYGON_API_KEY not set.')
        print('  1. Sign up free at https://massive.com')
        print('  2. Add  POLYGON_API_KEY=your_key  to .env.paper')
        sys.exit(1)

    print('=' * 65)
    print('POLYGON BACKFILL  -  Mar 7-15, 2026 gap  (optimized 2-phase)')
    print(f'Trading days : {", ".join(GAP_TRADING_DAYS)}')
    print(f'API key      : {POLYGON_API_KEY[:8]}...')
    print(f'Progress file: {PROGRESS_FILE}')
    print('=' * 65)

    progress = load_progress()

    # Migrate old progress format (3-phase) to new (2-phase) if needed
    if 'phase2_1m_symbols_done' in progress and 'phase2_symbols_done' not in progress:
        progress['phase2_symbols_done'] = progress.pop('phase2_1m_symbols_done')
        progress.pop('phase3_1h_symbols_done', None)
        save_progress(progress)
        print('[INFO] Migrated progress file from 3-phase to 2-phase format')

    conn = get_db_conn()

    try:
        run_preflight_test(conn)

        symbols = get_gapper_symbols(conn)

        # Phase 1: daily bars for ALL symbols (~1 min)
        phase1_daily(conn, progress)

        # Phase 2: minute bars 4am-12pm → split into 1m (8-12) + aggregated 1h (4-8)
        phase2_intraday(conn, symbols, progress)

        print('\n' + '=' * 65)
        print('BACKFILL COMPLETE')
        print(f'  1d rows inserted: {progress["total_inserted_1d"]:,}')
        print(f'  1m rows inserted: {progress["total_inserted_1m"]:,}')
        print(f'  1h rows inserted: {progress["total_inserted_1h"]:,}')
        print('=' * 65)
        print('\nVerify with:')
        print('  python research/maintenance/diagnostics/check_backfill_coverage.py')

    finally:
        conn.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n[STOPPED] Interrupted — progress saved, safe to resume')
