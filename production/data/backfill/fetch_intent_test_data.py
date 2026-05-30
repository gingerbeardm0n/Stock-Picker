#!/usr/bin/env python3
"""
Intent Test Data Fetcher
========================
Pulls minute bars from Polygon for specific symbols on specific test dates,
loads them into TimescaleDB stock_candles_1m so the simulator can run on them.

Usage:
    python production/data/backfill/fetch_intent_test_data.py

Test cases (max_loss_hit sessions where we verify simulator halts correctly):
    2024-03-06: IBD, APM, AISP   (file 0989 — -$15k IBD, kept trading)
    2024-09-20: GSIW, BZI, GDHG, LFLY  (file 1014 — GSIW revenge spiral, -$7.5k)
    2025-04-01: MLGO, ICCT, DATS, GRRI  (file 0985 — -$18k MLGO, kept trading)
"""
import os
import sys
import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../../.env.paper'))

POLYGON_API_KEY = os.getenv('POLYGON_API_KEY', '')
DB_CONN = os.getenv(
    'TIMESCALE_CONNECTION_STRING',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)
POLYGON_BASE = 'https://api.polygon.io'
ET = pytz.timezone('America/New_York')
UTC = pytz.UTC

# Free tier: 5 calls/min → sleep 13s between calls to be safe
SLEEP = 13

# ── Test cases ────────────────────────────────────────────────────────────────
TEST_CASES = [
    {
        'date': '2024-03-06',
        'file_num': '0989',
        'title': "Rollercoaster day — IBD -$15k, kept trading",
        'symbols': ['IBD', 'APM', 'AISP'],
        'expected_behavior': 'DAILY_MAX_LOSS fires after IBD trade. No entries on APM/AISP.',
    },
    {
        'date': '2024-09-20',
        'file_num': '1014',
        'title': "GSIW revenge spiral — -$7.5k",
        'symbols': ['GSIW', 'BZI', 'GDHG', 'LFLY'],
        'expected_behavior': 'DAILY_MAX_LOSS or GREEN_TO_RED fires after first GSIW loss. No re-entries.',
    },
    {
        'date': '2025-04-01',
        'file_num': '0985',
        'title': "MLGO -$18k, kept trading",
        'symbols': ['MLGO', 'ICCT', 'DATS', 'GRRI'],
        'expected_behavior': 'DAILY_MAX_LOSS fires on MLGO. No subsequent entries.',
    },
]

def polygon_get(endpoint, params=None):
    """GET Polygon endpoint. Handles 429 with backoff."""
    p = params or {}
    p['apiKey'] = POLYGON_API_KEY
    url = f"{POLYGON_BASE}{endpoint}"
    for attempt in range(3):
        r = requests.get(url, params=p, timeout=30)
        if r.status_code == 429:
            wait = 65
            print(f"    429 rate limit — waiting {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code != 200:
            print(f"    HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        if data.get('status') in ('ERROR', 'NOT_AUTHORIZED'):
            print(f"    API error: {data.get('error') or data.get('message')}")
            return None
        return data
    return None

def ms_to_utc(ms):
    """Convert Polygon millisecond epoch to UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)

def fetch_minute_bars(symbol, date_str):
    """
    Fetch 1-minute bars for symbol on date_str (YYYY-MM-DD).
    Returns list of bar dicts or [].
    Window: 4:00am - 12:30pm ET (covers premarket + trading window).
    """
    endpoint = f"/v2/aggs/ticker/{symbol}/range/1/minute/{date_str}/{date_str}"
    params = {
        'adjusted': 'true',
        'sort': 'asc',
        'limit': '50000',
    }
    data = polygon_get(endpoint, params)
    if not data or not data.get('results'):
        return []

    bars = []
    # Filter to 4am-12:30pm ET
    day_start = ET.localize(datetime.strptime(f"{date_str} 04:00", "%Y-%m-%d %H:%M"))
    day_end   = ET.localize(datetime.strptime(f"{date_str} 12:30", "%Y-%m-%d %H:%M"))
    day_start_ms = int(day_start.timestamp() * 1000)
    day_end_ms   = int(day_end.timestamp() * 1000)

    for r in data['results']:
        t_ms = r['t']
        if t_ms < day_start_ms or t_ms > day_end_ms:
            continue
        bars.append({
            'time': ms_to_utc(t_ms),
            'symbol': symbol,
            'open': r['o'],
            'high': r['h'],
            'low': r['l'],
            'close': r['c'],
            'volume': int(r['v']),
        })
    return bars

def insert_bars(conn, bars):
    """Insert bars into stock_candles_1m. Skip duplicates."""
    if not bars:
        return 0
    rows = [
        (b['time'], b['symbol'], b['open'], b['high'], b['low'], b['close'], b['volume'])
        for b in bars
    ]
    sql = """
        INSERT INTO stock_candles_1m (time, symbol, open, high, low, close, volume)
        VALUES %s
        ON CONFLICT (time, symbol) DO NOTHING
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, rows)
    conn.commit()
    return len(rows)

def check_existing(conn, symbol, date_str):
    """Return count of existing bars for symbol on date."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    day_start = ET.localize(day.replace(hour=4)).astimezone(UTC)
    day_end   = ET.localize(day.replace(hour=12, minute=30)).astimezone(UTC)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM stock_candles_1m WHERE symbol=%s AND time >= %s AND time <= %s",
            (symbol, day_start, day_end)
        )
        return cur.fetchone()[0]

# ── Main ──────────────────────────────────────────────────────────────────────

if not POLYGON_API_KEY:
    print("ERROR: POLYGON_API_KEY not set in .env.paper")
    sys.exit(1)

print(f"Connecting to DB...")
conn = psycopg2.connect(DB_CONN)
print("Connected.\n")

total_inserted = 0
total_skipped = 0

for tc in TEST_CASES:
    date = tc['date']
    print(f"{'='*60}")
    print(f"Test case: FILE {tc['file_num']} | {date}")
    print(f"  {tc['title']}")
    print(f"  Symbols: {tc['symbols']}")
    print(f"  Expected: {tc['expected_behavior']}")
    print()

    for symbol in tc['symbols']:
        existing = check_existing(conn, symbol, date)
        if existing > 0:
            print(f"  {symbol}: already have {existing} bars — skipping fetch")
            total_skipped += 1
            continue

        print(f"  {symbol}: fetching from Polygon...", end=' ', flush=True)
        bars = fetch_minute_bars(symbol, date)
        if bars:
            n = insert_bars(conn, bars)
            total_inserted += n
            print(f"inserted {n} bars ({bars[0]['time'].astimezone(ET).strftime('%H:%M')} - {bars[-1]['time'].astimezone(ET).strftime('%H:%M')} ET)")
        else:
            print(f"no data returned (symbol may not have traded this day)")

        time.sleep(SLEEP)

    print()

conn.close()
print(f"Done. Inserted {total_inserted} bars, skipped {total_skipped} already-present symbols.")
print()
print("Next step: run intent_test_runner.py to simulate these days and verify halt behavior.")
