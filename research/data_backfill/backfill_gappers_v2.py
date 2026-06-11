#!/usr/bin/env python3
"""
backfill_gappers_v2.py — Pass 2+3: targeted minute-bar backfill for movers.

v2 widens selection beyond open gaps so future strategies aren't blinded to
late movers (stocks that only show strength at 10:00-10:30) or volume-led
setups. A symbol-day qualifies for minute bars if ANY of:

  1. GAP:     open  >= prev_close * (1 + --min-gap/100)        [default 5%]
  2. MOVER:   high  >= prev_close * (1 + --min-high/100)       [default 10%]
              (daily high catches intraday spikes regardless of when they
               happened — including gap-and-crap faders)
  3. VOLUME:  volume >= 30d_avg_volume * --min-relvol           [default 3x]
              AND volume >= --min-abs-volume                    [default 500K]
              (absolute floor keeps thin stocks with tiny baselines out)

Price band on prev_close: --min-price/--max-price (default $1-$100, wider
than the live $2-$20 band, again for future-strategy headroom).

For each qualifying symbol-day: fetch 1-min bars 4am-12pm ET from Alpaca into
stock_candles_1m, then aggregate the 4-8am premarket minutes into
stock_candles_1h (the simulators read premarket from the hourly table).

Prerequisite: stock_candles_1d must already cover the range — run
backfill_daily_history.py (pass 1) first.

Usage:
    python research/data_backfill/backfill_gappers_v2.py --start 2020-01-01 --end 2020-12-31 --dry-run
    python research/data_backfill/backfill_gappers_v2.py --start 2020-01-01 --end 2020-12-31
    python research/data_backfill/backfill_gappers_v2.py --start 2020-01-01 --end 2020-12-31 --resume
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))

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

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

DB_CONN = os.getenv(
    'TIMESCALE_CONNECTION_STRING',
    'postgresql://postgres:yourpassword@localhost:5432/stockdata',
)

ET = pytz.timezone('US/Eastern')

FETCH_START_HOUR = 4
FETCH_END_HOUR = 12


def progress_path(start: str, end: str) -> Path:
    return Path(__file__).parent / f'backfill_gappers_v2_progress_{start}_{end}.json'


def load_progress(pfile: Path) -> dict:
    if pfile.exists():
        with pfile.open() as f:
            return json.load(f)
    return {'completed_dates': [], 'total_inserted': 0, 'errors': []}


def save_progress(pfile: Path, p: dict) -> None:
    p['last_updated'] = datetime.now().isoformat()
    with pfile.open('w') as f:
        json.dump(p, f, indent=2)


def find_movers_for_day(conn, trading_date: date, args) -> list[dict]:
    """
    Union-trigger selection from stock_candles_1d:
    gap-at-open OR intraday-high mover OR volume spike.
    Returns rows tagged with which triggers fired, sorted by gap_high desc.
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            t.symbol,
            prev.close                                                      AS prior_close,
            t.open, t.high, t.close, t.volume,
            ROUND(((t.open - prev.close) / prev.close * 100)::numeric, 2)   AS gap_open,
            ROUND(((t.high - prev.close) / prev.close * 100)::numeric, 2)   AS gap_high,
            ROUND((t.volume / NULLIF(stats.avg_vol30, 0))::numeric, 2)      AS rel_vol,
            CASE WHEN t.high > t.low
                 THEN ROUND(((t.high - t.close) / (t.high - t.low))::numeric, 3)
                 ELSE NULL END                                              AS upper_wick_ratio
        FROM stock_candles_1d t
        JOIN LATERAL (
            SELECT close
            FROM stock_candles_1d p
            WHERE p.symbol = t.symbol AND p.time < t.time
            ORDER BY p.time DESC
            LIMIT 1
        ) prev ON true
        LEFT JOIN LATERAL (
            SELECT avg(volume) AS avg_vol30
            FROM (
                SELECT volume
                FROM stock_candles_1d p
                WHERE p.symbol = t.symbol AND p.time < t.time
                ORDER BY p.time DESC
                LIMIT 30
            ) w
        ) stats ON true
        WHERE t.time::date = %(day)s
          AND prev.close BETWEEN %(min_price)s AND %(max_price)s
          AND (
                t.open >= prev.close * (1.0 + %(min_gap)s / 100.0)
             OR t.high >= prev.close * (1.0 + %(min_high)s / 100.0)
             OR (stats.avg_vol30 > 0
                 AND t.volume >= stats.avg_vol30 * %(min_relvol)s
                 AND t.volume >= %(min_abs_volume)s)
          )
        ORDER BY gap_high DESC
        """,
        {
            'day': trading_date,
            'min_price': args.min_price,
            'max_price': args.max_price,
            'min_gap': args.min_gap,
            'min_high': args.min_high,
            'min_relvol': args.min_relvol,
            'min_abs_volume': args.min_abs_volume,
        },
    )
    rows = cursor.fetchall()
    cursor.close()
    out = []
    for r in rows:
        sym, prior, o, h, c, v, gap_open, gap_high, rel_vol, wick = r
        triggers = []
        if gap_open is not None and float(gap_open) >= args.min_gap:
            triggers.append('gap')
        if gap_high is not None and float(gap_high) >= args.min_high:
            triggers.append('mover')
        if rel_vol is not None and float(rel_vol) >= args.min_relvol and v >= args.min_abs_volume:
            triggers.append('vol')
        out.append({
            'symbol': sym,
            'prior_close': float(prior),
            'gap_open': float(gap_open) if gap_open is not None else None,
            'gap_high': float(gap_high) if gap_high is not None else None,
            'rel_vol': float(rel_vol) if rel_vol is not None else None,
            'upper_wick_ratio': float(wick) if wick is not None else None,
            'triggers': triggers,
        })
    return out


def symbols_with_minute_data(conn, symbols: list[str], trading_date: date) -> set[str]:
    if not symbols:
        return set()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT DISTINCT symbol FROM stock_candles_1m
        WHERE symbol = ANY(%s) AND time::date = %s
        """,
        (symbols, trading_date),
    )
    result = {row[0] for row in cursor.fetchall()}
    cursor.close()
    return result


def fetch_and_insert_minutes(conn, client, symbols: list[str], trading_date: date) -> int:
    """Fetch 1-min bars 4am-12pm ET and insert. Returns rows inserted, -1 on API error."""
    start_dt = ET.localize(datetime.combine(trading_date, datetime.min.time().replace(hour=FETCH_START_HOUR)))
    end_dt = ET.localize(datetime.combine(trading_date, datetime.min.time().replace(hour=FETCH_END_HOUR)))
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
                    bar.timestamp, symbol,
                    float(bar.open), float(bar.high), float(bar.low), float(bar.close),
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


def aggregate_premarket_hours(conn, symbols: list[str], trading_date: date) -> int:
    """
    Roll 4-8am ET minute bars up into stock_candles_1h for the fetched symbols.
    Simulators read premarket from the hourly table.
    """
    if not symbols:
        return 0
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO stock_candles_1h (time, symbol, open, high, low, close, volume, trade_count, vwap)
        SELECT
            time_bucket('1 hour', time) AS bucket,
            symbol,
            first(open, time),
            max(high),
            min(low),
            last(close, time),
            sum(volume),
            sum(trade_count),
            CASE WHEN sum(volume) > 0
                 THEN sum(COALESCE(vwap, close) * volume) / sum(volume)
                 ELSE NULL END
        FROM stock_candles_1m
        WHERE symbol = ANY(%s)
          AND (time AT TIME ZONE 'US/Eastern')::date = %s
          AND (time AT TIME ZONE 'US/Eastern')::time >= '04:00'
          AND (time AT TIME ZONE 'US/Eastern')::time < '08:00'
        GROUP BY bucket, symbol
        ON CONFLICT (time, symbol) DO NOTHING
        """,
        (symbols, trading_date, trading_date),
    )
    n = cursor.rowcount
    conn.commit()
    cursor.close()
    return n


def run_backfill(args) -> None:
    start = datetime.strptime(args.start, '%Y-%m-%d').date()
    end = datetime.strptime(args.end, '%Y-%m-%d').date()
    trading_days = get_trading_days(start, end)

    pfile = progress_path(args.start, args.end)
    progress = load_progress(pfile)

    logger.info('=' * 70)
    logger.info('  MOVER-TARGETED MINUTE BAR BACKFILL (v2: gap OR high OR volume)')
    logger.info('=' * 70)
    logger.info(f'  Range        : {args.start} -> {args.end}  ({len(trading_days)} trading days)')
    logger.info(f'  Price band   : prev close ${args.min_price}-${args.max_price}')
    logger.info(f'  Triggers     : gap>={args.min_gap}%  OR  high>={args.min_high}%  OR  '
                f'relvol>={args.min_relvol}x (abs>={args.min_abs_volume:,})')
    logger.info(f'  Window       : {FETCH_START_HOUR}am-{FETCH_END_HOUR}pm ET, 1-min bars + premarket 1h rollup')
    logger.info(f'  Dry run      : {args.dry_run}')
    logger.info(f'  Progress     : {pfile.name} ({len(progress["completed_dates"])} dates done)')
    logger.info('')

    if progress['completed_dates'] and not (args.resume or args.dry_run):
        logger.info('Existing progress found. Add --resume to continue, or delete the progress file.')
        return

    conn = psycopg2.connect(DB_CONN)
    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)

    wall_start = time.perf_counter()
    total_inserted = progress.get('total_inserted', 0)
    total_movers = 0
    trigger_counts = {'gap': 0, 'mover': 0, 'vol': 0}
    errors = 0

    for i, day in enumerate(trading_days, 1):
        day_str = str(day)
        if day_str in progress['completed_dates']:
            continue

        movers = find_movers_for_day(conn, day, args)
        if not movers:
            logger.info(f'[{i:3d}/{len(trading_days)}] {day_str}  0 movers (no daily data for this date?)')
            if not args.dry_run:
                progress['completed_dates'].append(day_str)
                save_progress(pfile, progress)
            continue

        total_movers += len(movers)
        for m in movers:
            for t in m['triggers']:
                trigger_counts[t] += 1

        symbols_all = [m['symbol'] for m in movers]
        have = symbols_with_minute_data(conn, symbols_all, day)
        to_fetch = [s for s in symbols_all if s not in have]

        top3 = ', '.join(
            f"{m['symbol']}(hi+{m['gap_high']:.0f}%/{'+'.join(m['triggers'])})"
            for m in movers[:3]
        )
        logger.info(
            f'[{i:3d}/{len(trading_days)}] {day_str}  {len(movers):4d} movers  '
            f'fetch={len(to_fetch):4d} skip={len(have):4d}  top: {top3}'
        )

        if args.dry_run:
            continue

        if to_fetch:
            inserted = fetch_and_insert_minutes(conn, client, to_fetch, day)
            if inserted < 0:
                errors += 1
                progress['errors'].append({'date': day_str, 'symbols': len(to_fetch)})
                save_progress(pfile, progress)
                logger.warning('    -> API error; date NOT marked complete (retry with --resume)')
                time.sleep(5)
                continue
            hours = aggregate_premarket_hours(conn, to_fetch, day)
            total_inserted += inserted
            logger.info(f'    -> {inserted:,} minute bars, {hours:,} premarket hour bars')

        progress['completed_dates'].append(day_str)
        progress['total_inserted'] = total_inserted
        save_progress(pfile, progress)
        time.sleep(0.5)

    conn.close()
    elapsed = time.perf_counter() - wall_start
    logger.info('')
    logger.info('=' * 70)
    logger.info('  COMPLETE' + (' (DRY RUN — no fetches, no writes)' if args.dry_run else ''))
    logger.info('=' * 70)
    logger.info(f'  Symbol-days qualified : {total_movers:,}')
    logger.info(f'  Trigger hits          : gap={trigger_counts["gap"]:,}  '
                f'mover={trigger_counts["mover"]:,}  vol={trigger_counts["vol"]:,}')
    logger.info(f'  Minute bars inserted  : {total_inserted:,}')
    logger.info(f'  Errors                : {errors}')
    logger.info(f'  Time                  : {elapsed / 60:.1f} min')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Mover-targeted minute bar backfill (pass 2+3).')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show qualifying counts per day; no API calls, no writes')
    parser.add_argument('--min-gap', type=float, default=5.0, help='Trigger 1: open gap %% (default 5)')
    parser.add_argument('--min-high', type=float, default=10.0, help='Trigger 2: high vs prev close %% (default 10)')
    parser.add_argument('--min-relvol', type=float, default=3.0, help='Trigger 3: volume vs 30d avg (default 3x)')
    parser.add_argument('--min-abs-volume', type=int, default=500_000,
                        help='Trigger 3 floor: min absolute day volume (default 500K)')
    parser.add_argument('--min-price', type=float, default=1.0, help='Min prev close (default $1)')
    parser.add_argument('--max-price', type=float, default=100.0, help='Max prev close (default $100)')
    args = parser.parse_args()

    try:
        run_backfill(args)
    except KeyboardInterrupt:
        logger.info('\n[STOPPED] Progress saved. Add --resume to continue.')
