"""Backfill 1-minute bars for the stocks Ross Cameron actually traded.

Why: an Oct 8 2026 check found only ~41% of Ross's dated trades (parsed from the corpus
summaries) had minute bars in stock_candles_1m. The main backfill universe is a snapshot
list of $1-$20 tickers, so names that later delisted / renamed / fell under $1 are missing
(survivorship), and minute bars only span 8:00-12:00 ET.

This builds a separate, self-contained dataset so the main backtest universe is NOT
changed (sealed / Gate 1 results stay comparable):

  ross_trade_ledger     one row per trade parsed from the TRADES tables in
                        "Ross Cameron Day Trading Videos/extractions/TRANSCRIPT_SUMMARIES_*.md",
                        with the inferred trade_date (highest-volume candidate day)
  ross_trade_bars_1m    Alpaca SIP 1-minute bars, 04:00-12:00 ET, for every candidate day
                        (video upload date and the 4 calendar days before it)
  ross_trade_bars_1d    Alpaca SIP daily bars, 45 days before each trade date through it
  ross_backfill_done    resume markers (re-running skips finished work)

Alpaca's free plan serves full SIP history older than 15 minutes, including delisted
tickers (pilot-verified on SMFL, SYTA, LLAP).

Usage (local TimescaleDB up; Alpaca key from production/.env.paper):
    python research/data_backfill/backfill_ross_ledger.py            # full run, resumable
    python research/data_backfill/backfill_ross_ledger.py --report   # coverage report only
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import psycopg2
import psycopg2.extras
import pytz
from dotenv import load_dotenv

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CORPUS = os.environ.get('ROSS_CORPUS_DIR',
                        r'C:/Repositories/Stock-Picker/Ross Cameron Day Trading Videos')
DSN = os.environ.get('STOCKDATA_DSN', 'postgresql://postgres:changeme123@localhost:5432/stockdata')
ENV_FILE = os.environ.get('ALPACA_ENV_FILE', r'C:/Repositories/Stock-Picker/production/.env.paper')
ET = pytz.timezone('America/New_York')
LOOKBACK_DAYS = 4          # upload date can lag the trade day (weekends, next-day uploads)
SYMBOLS_PER_REQUEST = 50
DAILY_LOOKBACK = 45

DDL = """
CREATE TABLE IF NOT EXISTS ross_trade_ledger (
    file_num     text,
    trade_idx    int,
    symbol       varchar(10),
    raw_symbol   text,
    cells        jsonb,
    upload_date  date,
    trade_date   date,
    day_volume   bigint,
    status       text,       -- matched | no_bars | no_date
    PRIMARY KEY (file_num, trade_idx)
);
CREATE TABLE IF NOT EXISTS ross_trade_bars_1m (
    symbol varchar(10), time timestamptz, open double precision, high double precision,
    low double precision, close double precision, volume double precision,
    vwap double precision, trade_count double precision,
    PRIMARY KEY (symbol, time)
);
CREATE TABLE IF NOT EXISTS ross_trade_bars_1d (
    symbol varchar(10), time timestamptz, open double precision, high double precision,
    low double precision, close double precision, volume double precision,
    vwap double precision, trade_count double precision,
    PRIMARY KEY (symbol, time)
);
CREATE TABLE IF NOT EXISTS ross_backfill_done (kind text, key text, PRIMARY KEY (kind, key));
"""


# ── corpus parsing ────────────────────────────────────────────────────────────

def parse_trades():
    """Yield (file_num, trade_idx, symbol, raw_symbol, cells) from every summary chunk."""
    paths = sorted(glob.glob(os.path.join(CORPUS, 'extractions', 'TRANSCRIPT_SUMMARIES_[0-9]*.md')))
    for path in paths:
        cur, in_trades = None, False
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                m = re.match(r'FILE (\d{4})', line)
                if m:
                    cur, in_trades = m.group(1), False
                    continue
                if line.startswith('TRADES:'):
                    in_trades = True
                    continue
                if line.startswith(('TRADE_MECHANICS:', 'SUMMARY:', 'METADATA:')):
                    in_trades = False
                    continue
                if in_trades and cur and line.startswith('|'):
                    cells = [c.strip() for c in line.strip().strip('|').split('|')]
                    if len(cells) >= 2 and cells[0].isdigit():
                        raw = cells[1]
                        sym = re.sub(r'[^A-Z]', '', raw.upper())
                        yield cur, int(cells[0]), sym if 1 <= len(sym) <= 5 else None, raw, cells


def load_ledger(conn):
    fmap = json.load(open(os.path.join(CORPUS, 'extractions', 'file_video_id_map.json'), encoding='utf-8'))
    # Some FILEs appear in more than one chunk (re-extractions); the later entry wins.
    by_key = {}
    for fnum, idx, sym, raw, cells in parse_trades():
        ud = (fmap.get(fnum) or {}).get('upload_date')
        upload = datetime.strptime(ud, '%Y%m%d').date() if ud else None
        by_key[(fnum, idx)] = (fnum, idx, sym, raw, json.dumps(cells), upload,
                               'no_date' if (upload is None or sym is None) else None)
    rows = list(by_key.values())
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, """
            INSERT INTO ross_trade_ledger (file_num, trade_idx, symbol, raw_symbol, cells, upload_date, status)
            VALUES %s
            ON CONFLICT (file_num, trade_idx) DO UPDATE SET
              symbol = EXCLUDED.symbol, raw_symbol = EXCLUDED.raw_symbol, cells = EXCLUDED.cells,
              upload_date = EXCLUDED.upload_date""", rows)
    conn.commit()
    print(f'ledger: {len(rows)} trades parsed, {sum(1 for r in rows if r[6] is None)} with symbol + date', flush=True)


# ── Alpaca fetching ───────────────────────────────────────────────────────────

def _client():
    load_dotenv(ENV_FILE)
    return StockHistoricalDataClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])


def _fetch(client, symbols, tf, start, end):
    """Bars dict {symbol: [Bar]}; retries on rate limits / transient errors."""
    for attempt in range(6):
        try:
            req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=tf, start=start, end=end,
                                   feed=DataFeed.SIP)
            return client.get_stock_bars(req).data
        except Exception as e:  # noqa: BLE001 — alpaca-py raises a mix of APIError / requests errors
            msg = str(e)
            if 'invalid symbol' in msg.lower() and len(symbols) > 1:
                # one bad ticker poisons the batch — split and retry halves
                mid = len(symbols) // 2
                out = dict(_fetch(client, symbols[:mid], tf, start, end))
                out.update(_fetch(client, symbols[mid:], tf, start, end))
                return out
            if 'invalid symbol' in msg.lower():
                return {}
            wait = 2 ** attempt * 5 if '429' in msg or 'rate' in msg.lower() else 2 ** attempt
            print(f'  retry {attempt + 1} after {type(e).__name__}: {msg[:100]} (sleep {wait}s)', flush=True)
            time.sleep(wait)
    print(f'  GAVE UP on {len(symbols)} symbols {start:%Y-%m-%d}', flush=True)
    return {}


def _rows(data):
    for sym, bars in data.items():
        for b in bars:
            yield (sym, b.timestamp, b.open, b.high, b.low, b.close, b.volume, b.vwap, b.trade_count)


def _insert(conn, table, data):
    rows = list(_rows(data))
    if rows:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur, f'INSERT INTO {table} VALUES %s ON CONFLICT (symbol, time) DO NOTHING', rows)
    return len(rows)


def _done(conn, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT key FROM ross_backfill_done WHERE kind = %s', (kind,))
        return {r[0] for r in cur.fetchall()}


def _mark(conn, kind, key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO ross_backfill_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (kind, key))
    conn.commit()


def fetch_minute(conn, client):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT symbol, upload_date FROM ross_trade_ledger "
                    "WHERE symbol IS NOT NULL AND upload_date IS NOT NULL")
        pairs = cur.fetchall()
    by_day = defaultdict(set)
    for sym, upload in pairs:
        for back in range(LOOKBACK_DAYS + 1):
            d = upload - timedelta(days=back)
            if d.weekday() < 5:
                by_day[d].add(sym)
    done = _done(conn, 'minute')
    days = sorted(d for d in by_day if d.isoformat() not in done)
    print(f'minute: {len(by_day)} candidate days, {len(days)} to fetch', flush=True)
    t0, total = time.time(), 0
    for i, d in enumerate(days, 1):
        syms = sorted(by_day[d])
        start = ET.localize(datetime(d.year, d.month, d.day, 4, 0))
        end = ET.localize(datetime(d.year, d.month, d.day, 12, 0))
        for j in range(0, len(syms), SYMBOLS_PER_REQUEST):
            total += _insert(conn, 'ross_trade_bars_1m',
                             _fetch(client, syms[j:j + SYMBOLS_PER_REQUEST], TimeFrame.Minute, start, end))
        conn.commit()
        _mark(conn, 'minute', d.isoformat())
        if i % 100 == 0 or i == len(days):
            print(f'  minute {i}/{len(days)} days | {total:,} bars | {time.time() - t0:.0f}s', flush=True)


def assign_trade_dates(conn):
    """trade_date = candidate day with the most 04:00-12:00 volume for that symbol."""
    with conn.cursor() as cur:
        cur.execute('SET timescaledb.enable_vectorized_aggregation = off')
        cur.execute("""
            WITH vol AS (
                SELECT symbol, (time AT TIME ZONE 'America/New_York')::date AS d, sum(volume)::bigint AS v
                FROM ross_trade_bars_1m GROUP BY 1, 2
            ), best AS (
                SELECT DISTINCT ON (l.file_num, l.trade_idx) l.file_num, l.trade_idx, vol.d, vol.v
                FROM ross_trade_ledger l
                JOIN vol ON vol.symbol = l.symbol
                        AND vol.d BETWEEN l.upload_date - %s AND l.upload_date
                ORDER BY l.file_num, l.trade_idx, vol.v DESC
            )
            UPDATE ross_trade_ledger l SET trade_date = best.d, day_volume = best.v, status = 'matched'
            FROM best WHERE best.file_num = l.file_num AND best.trade_idx = l.trade_idx""", (LOOKBACK_DAYS,))
        cur.execute("UPDATE ross_trade_ledger SET status = 'no_bars' "
                    "WHERE status IS NULL OR (status <> 'matched' AND status <> 'no_date')")
    conn.commit()


def fetch_daily(conn, client):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, min(trade_date), max(trade_date) FROM ross_trade_ledger "
                    "WHERE status = 'matched' GROUP BY symbol")
        spans = cur.fetchall()
    done = _done(conn, 'daily')
    todo = [s for s in spans if s[0] not in done]
    print(f'daily: {len(spans)} symbols, {len(todo)} to fetch', flush=True)
    for i, (sym, lo, hi) in enumerate(todo, 1):
        start = ET.localize(datetime.combine(lo - timedelta(days=DAILY_LOOKBACK), datetime.min.time()))
        end = ET.localize(datetime.combine(hi + timedelta(days=1), datetime.min.time()))
        _insert(conn, 'ross_trade_bars_1d', _fetch(client, [sym], TimeFrame.Day, start, end))
        conn.commit()
        _mark(conn, 'daily', sym)
        if i % 200 == 0 or i == len(todo):
            print(f'  daily {i}/{len(todo)} symbols', flush=True)


# ── report ────────────────────────────────────────────────────────────────────

def report(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT extract(year FROM upload_date)::int, count(*),
                              count(*) FILTER (WHERE status = 'matched')
                       FROM ross_trade_ledger WHERE status <> 'no_date' GROUP BY 1 ORDER BY 1""")
        rows = cur.fetchall()
        print('\nyear  dated_trades  matched')
        for y, n, m in rows:
            print(f'{y}  {n:>12}  {m:>7} ({m / n:.0%})')
        n, m = sum(r[1] for r in rows), sum(r[2] for r in rows)
        print(f'ALL   {n:>12}  {m:>7} ({m / n:.0%})' if n else 'no rows')
        cur.execute("SELECT count(*) FROM ross_trade_ledger WHERE status = 'no_date'")
        print(f'undated or unparseable trades (not fetched): {cur.fetchone()[0]}')
        cur.execute("""SELECT raw_symbol, count(*) FROM ross_trade_ledger WHERE status = 'no_bars'
                       GROUP BY 1 ORDER BY 2 DESC""")
        flags = cur.fetchall()
    out_dir = os.path.join(REPO, 'research', 'analysis', 'outputs')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'ross_ledger_unmatched_symbols.csv')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('raw_symbol,trades\n')
        for s, c in flags:
            f.write(f'"{s}",{c}\n')
    print(f'{len(flags)} distinct unmatched symbols (likely typos / renames) -> {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true', help='coverage report only, no fetching')
    args = ap.parse_args()
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    if not args.report:
        load_ledger(conn)
        client = _client()
        fetch_minute(conn, client)
        assign_trade_dates(conn)
        fetch_daily(conn, client)
    else:
        assign_trade_dates(conn)
    report(conn)
    conn.close()
    print('DONE')


if __name__ == '__main__':
    sys.exit(main())
