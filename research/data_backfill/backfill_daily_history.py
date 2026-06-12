#!/usr/bin/env python3
"""
backfill_daily_history.py — Pass 1: daily bars for the full symbol universe.

Fetches daily OHLCV bars from Alpaca for every NASDAQ-traded symbol and
inserts them into stock_candles_1d. This is the foundation for the
gapper-targeted minute backfill (backfill_gappers_v2.py), which uses these
daily bars to decide which symbol-days deserve minute bars.

Designed to run one year at a time:
    python research/data_backfill/backfill_daily_history.py --year 2020
    python research/data_backfill/backfill_daily_history.py --year 2019 --resume
    python research/data_backfill/backfill_daily_history.py --start 2016-01-01 --end 2016-12-31

Universe: nasdaqtraded.txt (~12K symbols), snapshotted into the progress file
on first run so batches stay stable across resumes.

Known limitation (survivorship bias): symbols delisted before today are not in
the current universe file, so their history is missed. Acceptable for now.

Storage estimate: ~12K symbols x 252 days x 1 year = ~3M rows/year (~250MB).
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))

import argparse
import json
import logging
import time
from datetime import datetime, date, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
import pytz
import requests as http_requests
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import Config
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_CONN = os.getenv(
    'TIMESCALE_CONNECTION_STRING',
    'postgresql://postgres:yourpassword@localhost:5432/stockdata',
)

ET = pytz.timezone('US/Eastern')
NASDAQ_URL = 'https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt'
BATCH_SIZE = 200


def progress_path(start: str, end: str) -> Path:
    return Path(__file__).parent / f'backfill_daily_progress_{start}_{end}.json'


def fetch_universe() -> list[str]:
    """NASDAQ-traded symbol list (same source as the live runner)."""
    resp = http_requests.get(NASDAQ_URL, timeout=30)
    resp.raise_for_status()
    symbols = []
    for line in resp.text.splitlines()[1:]:
        parts = line.split('|')
        if len(parts) < 8 or parts[0] != 'Y':
            continue
        sym = parts[1].strip()
        # skip test issues, ETFs stay in (cheap, and some strategies may want them)
        if not sym or parts[3].strip() == 'Y':  # Test Issue flag
            continue
        # Alpaca rejects symbols with $ . = (units/warrants/preferreds variants)
        if any(c in sym for c in '$.='):
            continue
        symbols.append(sym)
    return sorted(set(symbols))


def load_progress(pfile: Path) -> dict:
    if pfile.exists():
        with pfile.open() as f:
            return json.load(f)
    return {'universe': None, 'completed_batches': [], 'total_inserted': 0}


def save_progress(pfile: Path, p: dict) -> None:
    p['last_updated'] = datetime.now().isoformat()
    with pfile.open('w') as f:
        json.dump(p, f)


def fetch_batch(client, symbols: list[str], start: date, end: date) -> list[tuple]:
    """Fetch daily bars for a symbol batch. Returns insert tuples. Raises on API error."""
    # Free tier rejects any request window touching "recent SIP data"
    # (roughly the last 15 minutes) — clamp the end to now - 16 min.
    end_dt = ET.localize(datetime.combine(end, datetime.max.time().replace(microsecond=0)))
    now_clamp = datetime.now(pytz.UTC).astimezone(ET) - timedelta(minutes=16)
    if end_dt > now_clamp:
        end_dt = now_clamp
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=ET.localize(datetime.combine(start, datetime.min.time())),
        end=end_dt,
    )
    response = client.get_stock_bars(request)
    values = []
    for symbol, bars in response.data.items():
        for bar in bars:
            values.append((
                bar.timestamp,
                symbol,
                float(bar.open),
                float(bar.high),
                float(bar.low),
                float(bar.close),
                int(bar.volume),
                int(bar.trade_count) if bar.trade_count else None,
                float(bar.vwap) if bar.vwap else None,
            ))
    return values


def run(start_str: str, end_str: str, resume: bool) -> None:
    start = datetime.strptime(start_str, '%Y-%m-%d').date()
    end = datetime.strptime(end_str, '%Y-%m-%d').date()

    pfile = progress_path(start_str, end_str)
    progress = load_progress(pfile)

    if progress['completed_batches'] and not resume:
        logger.info(f'{len(progress["completed_batches"])} batches already done for this range.')
        logger.info('Add --resume to continue, or delete the progress file to restart:')
        logger.info(f'  {pfile}')
        return

    if progress['universe'] is None:
        logger.info('Fetching NASDAQ-traded universe...')
        progress['universe'] = fetch_universe()
        save_progress(pfile, progress)
    universe = progress['universe']
    logger.info(f'Universe: {len(universe)} symbols')

    batches = [universe[i:i + BATCH_SIZE] for i in range(0, len(universe), BATCH_SIZE)]
    done = set(progress['completed_batches'])

    conn = psycopg2.connect(DB_CONN)
    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

    wall_start = time.perf_counter()
    total_inserted = progress.get('total_inserted', 0)
    errors = 0

    logger.info(f'Range {start_str} -> {end_str} | {len(batches)} batches of {BATCH_SIZE} | {len(done)} done')

    for i, batch in enumerate(batches):
        if i in done:
            continue
        try:
            values = fetch_batch(client, batch, start, end)
        except Exception as exc:
            errors += 1
            logger.warning(f'[batch {i:3d}/{len(batches)}] API error: {exc} — will retry on --resume')
            time.sleep(5)
            continue

        if values:
            cursor = conn.cursor()
            execute_values(
                cursor,
                """
                INSERT INTO stock_candles_1d
                    (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES %s
                ON CONFLICT (time, symbol) DO NOTHING
                """,
                values,
            )
            conn.commit()
            cursor.close()

        total_inserted += len(values)
        progress['completed_batches'].append(i)
        progress['total_inserted'] = total_inserted
        save_progress(pfile, progress)
        logger.info(f'[batch {i:3d}/{len(batches)}] {batch[0]}..{batch[-1]}  +{len(values):,} bars  (total {total_inserted:,})')
        time.sleep(0.3)  # ~200 req/min free-tier headroom

    conn.close()
    elapsed = time.perf_counter() - wall_start
    logger.info(f'DONE: {total_inserted:,} bars inserted, {errors} batch errors, {elapsed/60:.1f} min')
    if errors:
        logger.info('Re-run with --resume to retry failed batches.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Daily-bar backfill for the full symbol universe (pass 1).')
    parser.add_argument('--year', type=int, help='Shortcut: backfill one calendar year')
    parser.add_argument('--start', help='Start date YYYY-MM-DD')
    parser.add_argument('--end', help='End date YYYY-MM-DD')
    parser.add_argument('--resume', action='store_true', help='Continue from the progress file')
    args = parser.parse_args()

    if args.year:
        s, e = f'{args.year}-01-01', f'{args.year}-12-31'
    elif args.start and args.end:
        s, e = args.start, args.end
    else:
        parser.error('Provide --year or both --start and --end')

    try:
        run(s, e, args.resume)
    except KeyboardInterrupt:
        logger.info('\n[STOPPED] Progress saved. Add --resume to continue.')
