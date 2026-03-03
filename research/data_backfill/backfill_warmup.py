#!/usr/bin/env python3
"""
backfill_warmup.py — Fetch pre-period minute bars to seed relative volume calculation.

The relative volume filter in simulation_engine.py looks back ~20 days in
stock_candles_1m to compute the historical average volume at the same time
of day. For historical backtests, this data may not exist, causing all
stocks to get rel_vol = 0 and fail the entry filter.

This script fetches minute bars for a "warmup" period: it reads the unique
symbols from an already-completed gapper backfill, then downloads their
minute bars for a pre-period (typically the month before the backtest range).

Usage:
    # Step 1: backfill gapper days (already done)
    #   python data/backfill/backfill_gappers.py --start 2025-01-02 --end 2025-03-31

    # Step 2: fetch pre-period minute bars so rel_vol has historical context
    python data/backfill/backfill_warmup.py \\
        --symbols-from 2025-01-02 2025-03-31 \\
        --warmup-start 2024-12-01 --warmup-end 2024-12-31

How it works:
    1. Queries stock_candles_1m for unique symbols in the given date range
    2. For each trading day in the warmup range, batch-fetches all of those
       symbols' 1-minute bars (4am-12pm ET) from Alpaca
    3. Inserts with ON CONFLICT DO NOTHING — safe to re-run
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
import json
import logging
import time
from datetime import datetime, date
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from config import Config
from dotenv import load_dotenv
from utils.trading_calendar import get_trading_days

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

DB_CONN = os.getenv(
    'TIMESCALE_CONNECTION_STRING',
    'postgresql://postgres:yourpassword@localhost:5432/stockdata',
)

ET               = pytz.timezone('US/Eastern')
PROGRESS_FILE    = Path(__file__).parent / 'backfill_warmup_progress.json'
FETCH_START_HOUR = 4
FETCH_END_HOUR   = 12
BATCH_SIZE       = 200   # symbols per Alpaca API call


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with PROGRESS_FILE.open() as f:
            return json.load(f)
    return {'completed_dates': [], 'total_inserted': 0, 'errors': []}


def save_progress(p: dict) -> None:
    p['last_updated'] = datetime.now().isoformat()
    with PROGRESS_FILE.open('w') as f:
        json.dump(p, f, indent=2)


def get_unique_symbols(conn, period_start: str, period_end: str) -> list[str]:
    """Return all unique symbols that have minute bars in the given date range."""
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT symbol
        FROM stock_candles_1m
        WHERE time::date BETWEEN %s AND %s
        ORDER BY symbol
        """,
        (period_start, period_end),
    )
    symbols = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return symbols


def symbols_already_done(conn, symbols: list[str], trading_date: date) -> set[str]:
    """Return the subset of symbols that already have minute bars on trading_date."""
    if not symbols:
        return set()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT symbol
        FROM stock_candles_1m
        WHERE symbol = ANY(%s)
          AND time::date = %s
        """,
        (symbols, trading_date),
    )
    result = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return result


def fetch_and_insert_batch(
    conn,
    client: StockHistoricalDataClient,
    symbols: list[str],
    trading_date: date,
    dry_run: bool,
) -> int:
    """
    Fetch 1-minute bars (4am-12pm ET) for all symbols on trading_date.
    Returns bars inserted, or -1 on API error.
    """
    start_dt = ET.localize(
        datetime.combine(trading_date, datetime.min.time().replace(hour=FETCH_START_HOUR))
    )
    end_dt = ET.localize(
        datetime.combine(trading_date, datetime.min.time().replace(hour=FETCH_END_HOUR))
    )

    if dry_run:
        return 0

    inserted_total = 0
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Minute,
                start=start_dt,
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

            if values:
                cursor = conn.cursor()
                execute_values(
                    cursor,
                    """
                    INSERT INTO stock_candles_1m
                        (time, symbol, open, high, low, close, volume, trade_count, vwap)
                    VALUES %s
                    ON CONFLICT (time, symbol) DO NOTHING
                    """,
                    values,
                )
                conn.commit()
                cursor.close()
                inserted_total += len(values)

            time.sleep(0.3)  # gentle rate limiting between batches

        except Exception as exc:
            logger.warning(f'    Batch error ({batch[0]}..{batch[-1]}): {exc}')
            return -1

    return inserted_total


def run_warmup(
    period_start: str,
    period_end: str,
    warmup_start: str,
    warmup_end: str,
    resume: bool = False,
    dry_run: bool = False,
) -> None:
    conn   = psycopg2.connect(DB_CONN)
    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

    # Load symbol list from existing backfill
    logger.info(f'Loading symbols from stock_candles_1m ({period_start} → {period_end}) ...')
    symbols = get_unique_symbols(conn, period_start, period_end)

    if not symbols:
        logger.error('No symbols found in that period. Run backfill_gappers.py first.')
        conn.close()
        return

    warmup_days = get_trading_days(
        datetime.strptime(warmup_start, '%Y-%m-%d').date(),
        datetime.strptime(warmup_end,   '%Y-%m-%d').date(),
    )

    logger.info('=' * 65)
    logger.info('  WARMUP MINUTE BAR BACKFILL')
    logger.info('=' * 65)
    logger.info(f'  Symbols        : {len(symbols)} (from {period_start} → {period_end})')
    logger.info(f'  Warmup range   : {warmup_start} → {warmup_end} ({len(warmup_days)} trading days)')
    logger.info(f'  Batch size     : {BATCH_SIZE} symbols / API call')
    logger.info(f'  Batches/day    : {(len(symbols) - 1) // BATCH_SIZE + 1}')
    logger.info(f'  Dry run        : {dry_run}')
    logger.info('')

    progress = load_progress()

    if not resume and progress['completed_dates']:
        logger.info(f'Found existing progress ({len(progress["completed_dates"])} dates done).')
        try:
            ans = input('Reset and start fresh? (y/n): ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans == 'y':
            progress = {'completed_dates': [], 'total_inserted': 0, 'errors': []}
            save_progress(progress)
        else:
            logger.info('Use --resume to continue without this prompt.')
            conn.close()
            return

    wall_start     = time.perf_counter()
    total_inserted = progress.get('total_inserted', 0)
    total_errors   = 0

    for i, day in enumerate(warmup_days, 1):
        day_str = str(day)

        if day_str in progress['completed_dates']:
            logger.info(f'[{i:3d}/{len(warmup_days)}] {day_str}  SKIP (already done)')
            continue

        # Skip symbols that already have data on this day
        have_data = symbols_already_done(conn, symbols, day)
        to_fetch  = [s for s in symbols if s not in have_data]

        logger.info(
            f'[{i:3d}/{len(warmup_days)}] {day_str}  '
            f'fetch={len(to_fetch):3d}  skip={len(have_data):3d}'
        )

        if not to_fetch:
            progress['completed_dates'].append(day_str)
            save_progress(progress)
            continue

        inserted = fetch_and_insert_batch(conn, client, to_fetch, day, dry_run)

        if inserted >= 0:
            total_inserted            += inserted
            progress['total_inserted'] = total_inserted
            progress['completed_dates'].append(day_str)
            if not dry_run:
                logger.info(f'    → {inserted:,} bars inserted')
        else:
            total_errors += 1
            progress['errors'].append({'date': day_str})
            logger.warning(f'    → Error — will retry on --resume')

        save_progress(progress)
        time.sleep(0.5)

    conn.close()

    elapsed = time.perf_counter() - wall_start
    logger.info('')
    logger.info('=' * 65)
    logger.info('  WARMUP COMPLETE' + (' (DRY RUN)' if dry_run else ''))
    logger.info('=' * 65)
    logger.info(f'  Warmup days    : {len(warmup_days)}')
    logger.info(f'  Bars inserted  : {total_inserted:,}')
    logger.info(f'  Errors         : {total_errors}')
    logger.info(f'  Time           : {elapsed / 60:.1f} min')
    if not dry_run and total_inserted > 0:
        logger.info('')
        logger.info('  Relative volume should now be calculable for your backtest range.')
        logger.info('  Re-run simulate_date.py to verify trades fire, then launch sweep.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=(
            'Backfill pre-period minute bars so relative volume has historical context. '
            'Run after backfill_gappers.py completes.'
        )
    )
    parser.add_argument(
        '--symbols-from', nargs=2, required=True,
        metavar=('START', 'END'),
        help='Date range of existing gapper backfill (e.g. 2025-01-02 2025-03-31)',
    )
    parser.add_argument('--warmup-start', required=True, help='Pre-period start YYYY-MM-DD')
    parser.add_argument('--warmup-end',   required=True, help='Pre-period end   YYYY-MM-DD')
    parser.add_argument('--resume',    action='store_true', help='Skip already-completed dates')
    parser.add_argument('--dry-run',   action='store_true', help='Show plan without API calls')
    args = parser.parse_args()

    try:
        run_warmup(
            period_start  = args.symbols_from[0],
            period_end    = args.symbols_from[1],
            warmup_start  = args.warmup_start,
            warmup_end    = args.warmup_end,
            resume        = args.resume,
            dry_run       = args.dry_run,
        )
    except KeyboardInterrupt:
        logger.info('\n[STOPPED] Interrupted — progress saved. Add --resume to continue.')
