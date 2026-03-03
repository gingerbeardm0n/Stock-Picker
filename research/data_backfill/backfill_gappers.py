#!/usr/bin/env python3
"""
backfill_gappers.py — Targeted historical minute bar backfill for gapper stocks.

For each trading day in the target range, queries stock_candles_1d to find
stocks that gapped 10%+ with a prior close of $2-20. Fetches 1-minute bars
(4am-12pm ET) for only those stocks and inserts them into stock_candles_1m.

Why targeted?
- Full 4000-symbol backfill would take days and fill hundreds of GB
- Only gapper stocks (typically 20-100/day) are relevant to Ross Cameron's strategy
- Each day's gappers can be fetched in a single batch API call

Prerequisites:
- stock_candles_1m retention policy must be removed (run once):
    docker exec stockdata-timescale psql -U postgres -d stockdata \\
      -c "SELECT remove_retention_policy('stock_candles_1m');"
- stock_candles_1d must have data for the target range (it goes back to Dec 2024)

Usage:
    python data/backfill/backfill_gappers.py --start 2025-01-02 --end 2025-03-31
    python data/backfill/backfill_gappers.py --start 2025-01-02 --end 2025-03-31 --resume
    python data/backfill/backfill_gappers.py --start 2025-01-02 --end 2025-03-31 --dry-run
    python data/backfill/backfill_gappers.py --start 2025-01-02 --end 2025-12-31  # full year

Storage estimate:
    ~20-100 gappers/day × 480 bars (4am-12pm) × 60 trading days (Jan-Mar) ≈ 1-3M bars ≈ 300MB
    Full 2025 (252 days) ≈ 1-2 GB

Time estimate: ~15-45 minutes for a 3-month range
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

ET = pytz.timezone('US/Eastern')
PROGRESS_FILE = Path(__file__).parent / 'backfill_gappers_progress.json'

# ── Gapper criteria (matches simulation scanner) ───────────────────────────────
MIN_PRIOR_CLOSE = 2.0    # Prior day close must be >= $2
MAX_PRIOR_CLOSE = 20.0   # Prior day close must be <= $20
MIN_GAP_PCT     = 10.0   # Must gap up at least 10% from prior close

# ── Time window to fetch from Alpaca ──────────────────────────────────────────
# Full morning session: premarket (4am) + trading window (8am-12pm)
FETCH_START_HOUR = 4
FETCH_END_HOUR   = 12


# ── Progress helpers ───────────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with PROGRESS_FILE.open() as f:
            return json.load(f)
    return {
        'completed_dates': [],
        'total_inserted': 0,
        'errors': [],
    }


def save_progress(p: dict) -> None:
    p['last_updated'] = datetime.now().isoformat()
    with PROGRESS_FILE.open('w') as f:
        json.dump(p, f, indent=2)


# ── Database helpers ───────────────────────────────────────────────────────────

def find_gappers_for_day(conn, trading_date: date) -> list[dict]:
    """
    Query stock_candles_1d to find stocks that gapped 10%+ on trading_date
    with a prior close in the $2-20 range.

    Uses a LATERAL join to find each symbol's most recent prior daily bar,
    then filters by gap criteria. Returns list sorted by gap_pct descending.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            t.symbol,
            prev.close                                                AS prior_close,
            t.open                                                    AS open_price,
            ROUND(((t.open - prev.close) / prev.close * 100)::numeric, 2) AS gap_pct
        FROM stock_candles_1d t
        JOIN LATERAL (
            SELECT close
            FROM stock_candles_1d p
            WHERE p.symbol = t.symbol
              AND p.time < t.time
            ORDER BY p.time DESC
            LIMIT 1
        ) prev ON true
        WHERE t.time::date = %s
          AND prev.close BETWEEN %s AND %s
          AND t.open >= prev.close * (1.0 + %s / 100.0)
        ORDER BY gap_pct DESC
        """,
        (trading_date, MIN_PRIOR_CLOSE, MAX_PRIOR_CLOSE, MIN_GAP_PCT),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [
        {
            'symbol':      row[0],
            'prior_close': float(row[1]),
            'open_price':  float(row[2]),
            'gap_pct':     float(row[3]),
        }
        for row in rows
    ]


def symbols_with_minute_data(conn, symbols: list[str], trading_date: date) -> set[str]:
    """
    Return the subset of symbols that already have at least one minute bar
    in stock_candles_1m for trading_date. Used to skip re-fetching.
    """
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


# ── Alpaca fetch ───────────────────────────────────────────────────────────────

def fetch_and_insert(
    conn,
    client: StockHistoricalDataClient,
    symbols: list[str],
    trading_date: date,
    dry_run: bool,
) -> int:
    """
    Fetch 1-minute bars for all symbols on trading_date (4am-12pm ET).
    Inserts into stock_candles_1m using ON CONFLICT DO NOTHING.

    Returns:
        >= 0  : bars inserted (0 if API returned no data)
        -1    : API error — caller should NOT mark date as complete
    """
    start_dt = ET.localize(
        datetime.combine(
            trading_date,
            datetime.min.time().replace(hour=FETCH_START_HOUR),
        )
    )
    end_dt = ET.localize(
        datetime.combine(
            trading_date,
            datetime.min.time().replace(hour=FETCH_END_HOUR),
        )
    )

    if dry_run:
        logger.info(
            f'    [DRY RUN] Would fetch {len(symbols)} symbols '
            f'{start_dt.strftime("%H:%M")}-{end_dt.strftime("%H:%M")} ET'
        )
        return 0

    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbols,
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

        if not values:
            return 0

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
        return len(values)

    except Exception as exc:
        logger.warning(f'    API error: {exc}')
        return -1


# ── Main ───────────────────────────────────────────────────────────────────────

def run_backfill(
    start_date: str,
    end_date: str,
    resume: bool = False,
    dry_run: bool = False,
) -> None:
    start        = datetime.strptime(start_date, '%Y-%m-%d').date()
    end          = datetime.strptime(end_date,   '%Y-%m-%d').date()
    trading_days = get_trading_days(start, end)

    logger.info('=' * 65)
    logger.info('  GAPPER-TARGETED MINUTE BAR BACKFILL')
    logger.info('=' * 65)
    logger.info(f'  Date range   : {start_date} → {end_date}')
    logger.info(f'  Trading days : {len(trading_days)}')
    logger.info(f'  Criteria     : prior close ${MIN_PRIOR_CLOSE}-${MAX_PRIOR_CLOSE}, gap {MIN_GAP_PCT}%+')
    logger.info(f'  Time window  : {FETCH_START_HOUR}am-{FETCH_END_HOUR}pm ET  (1-min bars)')
    logger.info(f'  Dry run      : {dry_run}')
    logger.info('')

    progress = load_progress()

    if not resume and progress['completed_dates']:
        logger.info(f'Found existing progress ({len(progress["completed_dates"])} dates done).')
        logger.info('Use --resume to continue from where you left off,')
        logger.info('or delete backfill_gappers_progress.json to restart from scratch.')
        try:
            ans = input('Reset and start fresh? (y/n): ').strip().lower()
        except EOFError:
            ans = 'n'
        if ans == 'y':
            progress = {'completed_dates': [], 'total_inserted': 0, 'errors': []}
            save_progress(progress)
        else:
            logger.info('Tip: add --resume to continue without this prompt.')
            return

    conn   = psycopg2.connect(DB_CONN)
    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

    wall_start     = time.perf_counter()
    total_inserted = progress.get('total_inserted', 0)
    total_gappers  = 0
    total_errors   = 0

    for i, day in enumerate(trading_days, 1):
        day_str = str(day)

        if day_str in progress['completed_dates']:
            logger.info(f'[{i:3d}/{len(trading_days)}] {day_str}  SKIP (already done)')
            continue

        # Step 1: identify gappers from daily bars
        gappers = find_gappers_for_day(conn, day)

        if not gappers:
            logger.info(
                f'[{i:3d}/{len(trading_days)}] {day_str}  '
                f'0 gappers — no daily bar data for this date'
            )
            progress['completed_dates'].append(day_str)
            save_progress(progress)
            continue

        symbols_all    = [g['symbol'] for g in gappers]
        total_gappers += len(gappers)

        # Step 2: skip symbols already loaded
        have_data = symbols_with_minute_data(conn, symbols_all, day)
        to_fetch  = [s for s in symbols_all if s not in have_data]

        top3 = ', '.join(
            f"{g['symbol']}(+{g['gap_pct']:.0f}%)"
            for g in gappers[:3]
        )
        logger.info(
            f'[{i:3d}/{len(trading_days)}] {day_str}  '
            f'{len(gappers):3d} gappers  '
            f'fetch={len(to_fetch):3d}  skip={len(have_data):3d}  '
            f'top: {top3}'
        )

        if not to_fetch:
            progress['completed_dates'].append(day_str)
            save_progress(progress)
            continue

        # Step 3: fetch from Alpaca and insert
        inserted = fetch_and_insert(conn, client, to_fetch, day, dry_run)

        if inserted >= 0:
            total_inserted            += inserted
            progress['total_inserted'] = total_inserted
            progress['completed_dates'].append(day_str)
            if not dry_run:
                logger.info(f'    → {inserted:,} bars inserted')
        else:
            total_errors += 1
            progress['errors'].append({'date': day_str, 'symbols': len(to_fetch)})
            logger.warning(f'    → API error — date NOT marked complete (will retry on --resume)')

        save_progress(progress)
        time.sleep(0.5)  # gentle rate limiting between days

    conn.close()

    elapsed = time.perf_counter() - wall_start
    logger.info('')
    logger.info('=' * 65)
    logger.info('  BACKFILL COMPLETE' + (' (DRY RUN)' if dry_run else ''))
    logger.info('=' * 65)
    logger.info(f'  Trading days  : {len(trading_days)}')
    logger.info(f'  Gappers found : {total_gappers}')
    logger.info(f'  Bars inserted : {total_inserted:,}')
    logger.info(f'  Errors        : {total_errors}')
    logger.info(f'  Time          : {elapsed / 60:.1f} min')
    if not dry_run and total_inserted > 0:
        logger.info('')
        logger.info('  Suggested next steps:')
        logger.info(f'    python optimizer/sweep.py --start {start_date} --end {end_date} --workers 6')
        logger.info( '    python optimizer/analyze.py summary')


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=(
            'Targeted 1-min bar backfill for gapper stocks. '
            'Uses stock_candles_1d to identify which stocks gapped 10%+ on each day, '
            'then fetches only those bars from Alpaca (4am-12pm ET window).'
        )
    )
    parser.add_argument('--start',   required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end',     required=True, help='End date   YYYY-MM-DD')
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Skip dates already marked complete in the progress file',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Identify gappers and show what would be fetched — no API calls, no DB writes',
    )
    args = parser.parse_args()

    try:
        run_backfill(args.start, args.end, args.resume, args.dry_run)
    except KeyboardInterrupt:
        logger.info('\n[STOPPED] Interrupted — progress saved. Add --resume to continue.')
