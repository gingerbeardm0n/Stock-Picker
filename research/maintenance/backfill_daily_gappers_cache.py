#!/usr/bin/env python3
"""
Backfill daily_gappers cache for a historical date range.

Reads from stock_candles_1d (no API calls) and populates daily_gappers
for any dates not already cached. Run before backfill_rel_vol_historical.py
when extending the simulation range to new years.

Usage:
    python research/maintenance/backfill_daily_gappers_cache.py --start 2016-01-01 --end 2020-12-31
    python research/maintenance/backfill_daily_gappers_cache.py --start 2016-01-01 --end 2020-12-31 --status
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))

import psycopg2
from utils.query_helpers import StockDataDB

logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

DB_CONN = 'postgresql://postgres:changeme123@localhost:5432/stockdata'


def get_trading_days(start: date, end: date) -> list[date]:
    days, cur = [], start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def already_cached(conn, start: date, end: date) -> set[date]:
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT trade_date FROM daily_gappers WHERE trade_date >= %s AND trade_date <= %s",
        (start, end),
    )
    result = {row[0] for row in cur.fetchall()}
    cur.close()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end',   required=True, help='YYYY-MM-DD')
    ap.add_argument('--status', action='store_true', help='Show coverage and exit')
    ap.add_argument('--min-gap', type=float, default=5.0,
                    help='Min gap%% to store (default 5.0 — keeps full range for Optuna tuning)')
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    trading_days = get_trading_days(start, end)

    conn = psycopg2.connect(DB_CONN)
    cached = already_cached(conn, start, end)
    conn.close()

    missing = [d for d in trading_days if d not in cached]

    if args.status:
        logger.info(f"Range: {start} -> {end}  ({len(trading_days)} trading days)")
        logger.info(f"Cached: {len(cached)}  Missing: {len(missing)}")
        if missing:
            logger.info(f"First missing: {missing[0]}  Last missing: {missing[-1]}")
        return

    if not missing:
        logger.info(f"All {len(trading_days)} days already cached. Nothing to do.")
        return

    logger.info(f"Backfilling daily_gappers: {len(missing)} days  ({start} -> {end})")
    logger.info(f"min_gap={args.min_gap}%  (no API calls — reads stock_candles_1d only)")

    total_inserted = 0
    errors = 0

    with StockDataDB() as db:
        for i, d in enumerate(missing, 1):
            try:
                n = db.refresh_daily_gappers(d, min_gap_pct=args.min_gap)
                total_inserted += n
                if i % 50 == 0 or i == len(missing):
                    logger.info(f"  [{i}/{len(missing)}] {d}  inserted={n}  total={total_inserted:,}")
            except Exception as e:
                logger.warning(f"  [{i}/{len(missing)}] {d}  ERROR: {e}")
                errors += 1

    logger.info(f"Done. {total_inserted:,} rows inserted across {len(missing) - errors} days. Errors: {errors}")


if __name__ == '__main__':
    main()
