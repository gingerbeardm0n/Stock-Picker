#!/usr/bin/env python3
"""
Backfill rel_vol_30d for all historical trading days.

Definition:
    rel_vol_30d at minute X  =  cum_vol_today(4am→X)  /  avg_cum_vol(4am→X, past 30 trading days)

    cum_vol_today = premarket volume (4am–8am, from stock_candles_1h)
                  + cumulative intraday volume (8am→X, from stock_candles_1m)

Two-phase process:
  Phase 1 — Build rel_vol_cum_cache for any trading day not yet in the table.
             One row per (trade_date, symbol, minute_of_day).
             Must run in chronological order so Phase 2 has full lookback.
             Batch mode (default): one query per calendar month — 10-20x faster
             than per-day mode.  Use --no-batch to fall back to per-day.

  Phase 2 — Write rel_vol_30d into stock_candles_1m for each trading day.
             For each bar: look up cum_total from cache, divide by 30-day avg.
             Only processes dates not already in the progress log.

Progress is saved to backfill_rel_vol_progress.json so runs can be interrupted
and resumed safely.  Both phases append to their own completed-date lists.

Usage:
    python research/maintenance/backfill_rel_vol_historical.py
    python research/maintenance/backfill_rel_vol_historical.py --phase 1
    python research/maintenance/backfill_rel_vol_historical.py --phase 2
    python research/maintenance/backfill_rel_vol_historical.py --start 2021-01-01 --end 2022-12-31
    python research/maintenance/backfill_rel_vol_historical.py --status
    python research/maintenance/backfill_rel_vol_historical.py --phase 1 --no-batch  # per-day fallback
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

DB_CONN = 'postgresql://postgres:changeme123@localhost:5432/stockdata'
SCHEMA  = 'public'

ET_TZ  = ZoneInfo('America/New_York')
UTC_TZ = ZoneInfo('UTC')

LOOKBACK_DAYS  = 30
MINUTE_START   = 8     # ET hour: minute bar window start (inclusive)
MINUTE_END     = 13    # ET hour: minute bar window end   (exclusive)
HOUR_START_PM  = 4     # ET hour: premarket hourly start  (inclusive)
HOUR_END_PM    = 8     # ET hour: premarket hourly end    (exclusive)

PROGRESS_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', 'production', 'data', 'backfill',
    'backfill_rel_vol_progress.json',
)


# ── ET/UTC helpers ────────────────────────────────────────────────────────────

def et_at(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=ET_TZ)

def to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


# ── Progress tracking ─────────────────────────────────────────────────────────

def load_progress() -> dict:
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return {'phase1_done': [], 'phase2_done': [], 'last_update': None}

def save_progress(p: dict) -> None:
    p['last_update'] = datetime.now().isoformat(timespec='seconds')
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(p, f, indent=2)


# ── DB helpers ────────────────────────────────────────────────────────────────

def connect_with_retry(max_attempts: int = 8, base_wait: int = 10):
    """Connect to DB, retrying if PostgreSQL is still recovering from a crash."""
    import psycopg2 as _pg
    for attempt in range(max_attempts):
        try:
            return _pg.connect(DB_CONN)
        except _pg.OperationalError as e:
            if attempt == max_attempts - 1:
                raise
            wait = base_wait * (2 ** attempt)  # 10, 20, 40, 80, 160 ...
            logger.warning(f"  DB connect failed (attempt {attempt+1}/{max_attempts}): {e}")
            logger.info(f"  PostgreSQL recovering — waiting {wait}s before retry...")
            time.sleep(wait)


def get_all_trading_days(conn, start: date, end: date) -> list[date]:
    """All dates that exist in tradable_stocks_by_date."""
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT date FROM tradable_stocks_by_date "
        "WHERE date >= %s AND date <= %s ORDER BY date",
        (start.isoformat(), end.isoformat()),
    )
    return [r[0] for r in cur.fetchall()]


def get_cached_dates(conn) -> set[date]:
    """Dates already present in rel_vol_cum_cache."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT DISTINCT trade_date FROM rel_vol_cum_cache")
        return {r[0] for r in cur.fetchall()}
    except psycopg2.errors.UndefinedTable:
        conn.rollback()
        return set()


# ── Phase 1: Build rel_vol_cum_cache ─────────────────────────────────────────

def ensure_cache_table(conn) -> None:
    """Create rel_vol_cum_cache table + index if not yet present."""
    sql = f"""
    CREATE TABLE IF NOT EXISTS {SCHEMA}.rel_vol_cum_cache (
        trade_date    date             NOT NULL,
        symbol        varchar(10)      NOT NULL,
        minute_of_day int              NOT NULL,
        cum_total     double precision NOT NULL,
        PRIMARY KEY (trade_date, symbol, minute_of_day)
    );
    CREATE INDEX IF NOT EXISTS rel_vol_cum_cache_sym_min_date
        ON {SCHEMA}.rel_vol_cum_cache (symbol, minute_of_day, trade_date);
    """
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def build_cache_month_batch(conn, dates_in_month: list[date]) -> int:
    """
    Populate rel_vol_cum_cache for a full calendar month in ONE query.

    Optimizations vs per-day:
      - Single DB round-trip covers all ~20 trading days
      - Plain INSERT (no ON CONFLICT) — caller ensures dates not already cached
      - One COMMIT for the whole month
      - TimescaleDB scans all day-chunks in parallel via one query plan

    Returns number of rows inserted.
    """
    if not dates_in_month:
        return 0

    # Cover entire month: premarket 4am first_day → 8am last_day+1
    # Minute bars 8am first_day → end_hour last_day+1
    first, last = dates_in_month[0], dates_in_month[-1]

    pm_start = to_utc(et_at(first, HOUR_START_PM))
    pm_end   = to_utc(et_at(last + timedelta(days=1), HOUR_END_PM))
    m_start  = to_utc(et_at(first, MINUTE_START))
    m_end    = to_utc(et_at(last + timedelta(days=1), MINUTE_END))

    sql = f"""
    SET LOCAL work_mem = '128MB';
    SET LOCAL max_parallel_workers_per_gather = 0;

    INSERT INTO {SCHEMA}.rel_vol_cum_cache (trade_date, symbol, minute_of_day, cum_total)
    SELECT
        m.trade_date,
        m.symbol,
        m.minute_of_day,
        COALESCE(p.premarket_vol, 0) + m.cum_minute_vol
    FROM (
        SELECT
            DATE(time AT TIME ZONE 'America/New_York')                   AS trade_date,
            symbol,
            (EXTRACT(HOUR   FROM time AT TIME ZONE 'America/New_York')::int * 60
             + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')::int) AS minute_of_day,
            SUM(volume) OVER (
                PARTITION BY symbol, DATE(time AT TIME ZONE 'America/New_York')
                ORDER BY time
            )::double precision AS cum_minute_vol
        FROM {SCHEMA}.stock_candles_1m
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ) m
    LEFT JOIN (
        SELECT
            DATE(time AT TIME ZONE 'America/New_York') AS trade_date,
            symbol,
            SUM(volume)::double precision              AS premarket_vol
        FROM {SCHEMA}.stock_candles_1h
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
        GROUP BY 1, 2
    ) p ON p.symbol = m.symbol AND p.trade_date = m.trade_date
    WHERE m.trade_date = ANY(%s::date[]);
    """

    date_array = [d.isoformat() for d in dates_in_month]
    with conn.cursor() as cur:
        cur.execute(sql, (m_start, m_end, pm_start, pm_end, date_array))
        rows = cur.rowcount
    conn.commit()
    return rows


def build_cache_for_date(conn, d: date) -> int:
    """
    Populate rel_vol_cum_cache for one trading day (per-day fallback mode).
    Used when --no-batch is specified or for re-running individual dates.
    """
    pm_start = to_utc(et_at(d, HOUR_START_PM))
    pm_end   = to_utc(et_at(d, HOUR_END_PM))
    m_start  = to_utc(et_at(d, MINUTE_START))
    m_end    = to_utc(et_at(d, MINUTE_END))

    sql = f"""
    SET LOCAL work_mem = '256MB';

    DROP TABLE IF EXISTS tmp_pm;
    DROP TABLE IF EXISTS tmp_min;

    CREATE TEMP TABLE tmp_pm ON COMMIT DROP AS
    SELECT symbol, SUM(volume)::double precision AS premarket_vol
    FROM {SCHEMA}.stock_candles_1h
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    GROUP BY symbol;

    CREATE TEMP TABLE tmp_min ON COMMIT DROP AS
    SELECT
        symbol,
        (EXTRACT(HOUR  FROM time AT TIME ZONE 'America/New_York')::int * 60
         + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')::int) AS minute_of_day,
        SUM(volume) OVER (PARTITION BY symbol ORDER BY time)::double precision AS cum_minute_vol
    FROM {SCHEMA}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz;

    INSERT INTO {SCHEMA}.rel_vol_cum_cache (trade_date, symbol, minute_of_day, cum_total)
    SELECT
        %s::date,
        m.symbol,
        m.minute_of_day,
        COALESCE(p.premarket_vol, 0) + m.cum_minute_vol
    FROM tmp_min m
    LEFT JOIN tmp_pm p ON p.symbol = m.symbol
    ON CONFLICT (trade_date, symbol, minute_of_day)
    DO UPDATE SET cum_total = EXCLUDED.cum_total;
    """

    with conn.cursor() as cur:
        cur.execute(sql, (pm_start, pm_end, m_start, m_end, d))
        rows = cur.rowcount
    conn.commit()
    return rows


# ── Phase 2: Populate rel_vol_30d in stock_candles_1m ────────────────────────

def backfill_rel_vol_for_date(conn, d: date) -> int:
    """
    For one trading day, compute rel_vol_30d = cum_total / avg_cum_total
    and UPDATE stock_candles_1m.

    avg_cum_total = average of cum_total at same (symbol, minute_of_day)
                   over the previous LOOKBACK_DAYS trading days.

    Returns number of rows updated.
    """
    m_start = to_utc(et_at(d, MINUTE_START))
    m_end   = to_utc(et_at(d, MINUTE_END))

    sql = f"""
    SET LOCAL work_mem = '512MB';

    -- 30-day rolling avg at each (symbol, minute_of_day) from cache
    DROP TABLE IF EXISTS tmp_avg;
    CREATE TEMP TABLE tmp_avg ON COMMIT DROP AS
    SELECT
        symbol,
        minute_of_day,
        AVG(cum_total)::double precision AS avg_cum_total
    FROM {SCHEMA}.rel_vol_cum_cache
    WHERE trade_date <  %s::date
      AND trade_date >= %s::date - INTERVAL '1 day' * %s
    GROUP BY symbol, minute_of_day;

    CREATE INDEX ON tmp_avg (symbol, minute_of_day);

    -- Today's bars with their minute_of_day
    DROP TABLE IF EXISTS tmp_today;
    CREATE TEMP TABLE tmp_today ON COMMIT DROP AS
    SELECT
        time,
        symbol,
        (EXTRACT(HOUR  FROM time AT TIME ZONE 'America/New_York')::int * 60
         + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')::int) AS minute_of_day
    FROM {SCHEMA}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz;

    -- Update rel_vol_30d
    UPDATE {SCHEMA}.stock_candles_1m m
       SET rel_vol_30d = CASE
               WHEN a.avg_cum_total > 0 THEN c.cum_total / a.avg_cum_total
               ELSE NULL
           END
      FROM tmp_today t
      JOIN {SCHEMA}.rel_vol_cum_cache c
        ON c.trade_date    = %s::date
       AND c.symbol        = t.symbol
       AND c.minute_of_day = t.minute_of_day
      LEFT JOIN tmp_avg a
        ON a.symbol        = t.symbol
       AND a.minute_of_day = t.minute_of_day
     WHERE m.time   = t.time
       AND m.symbol = t.symbol;
    """

    with conn.cursor() as cur:
        cur.execute(sql, (d, d, LOOKBACK_DAYS, m_start, m_end, d))
        rows = cur.rowcount
    conn.commit()
    return rows


# ── Phase 2 (fast): window function on cache → staging → bulk UPDATE ──────────

def build_rel_vol_staging(conn, start: date, end: date) -> int:
    """
    Compute rel_vol_30d for every (trade_date, symbol, minute_of_day) in
    [start, end] using a single window function query against rel_vol_cum_cache.

    Includes a 60-calendar-day lookback warmup before `start` so the first
    days in range have proper 30-trading-day averages.

    Stores results in rel_vol_staging (created if missing).
    Returns rows inserted/updated.
    """
    # Extend start backward to warm up the 30-day rolling window.
    # 60 calendar days covers ~42 trading days — enough cushion.
    warmup_start = start - timedelta(days=60)

    sql = f"""
    SET LOCAL work_mem = '256MB';

    CREATE TABLE IF NOT EXISTS {SCHEMA}.rel_vol_staging (
        trade_date    date             NOT NULL,
        symbol        varchar(10)      NOT NULL,
        minute_of_day int              NOT NULL,
        rel_vol_30d   double precision,
        PRIMARY KEY (trade_date, symbol, minute_of_day)
    );

    INSERT INTO {SCHEMA}.rel_vol_staging
        (trade_date, symbol, minute_of_day, rel_vol_30d)
    SELECT trade_date, symbol, minute_of_day, rel_vol_30d
    FROM (
        SELECT
            c.trade_date,
            c.symbol,
            c.minute_of_day,
            c.cum_total / NULLIF(
                AVG(c.cum_total) OVER (
                    PARTITION BY c.symbol, c.minute_of_day
                    ORDER BY c.trade_date
                    ROWS BETWEEN {LOOKBACK_DAYS} PRECEDING AND 1 PRECEDING
                ), 0
            ) AS rel_vol_30d
        FROM {SCHEMA}.rel_vol_cum_cache c
        WHERE c.trade_date >= %s   -- warmup_start (for lookback warmup)
          AND c.trade_date <= %s   -- end
    ) sub
    WHERE trade_date >= %s         -- actual start (discard warmup rows)
      AND trade_date <= %s         -- end
    ON CONFLICT (trade_date, symbol, minute_of_day)
    DO UPDATE SET rel_vol_30d = EXCLUDED.rel_vol_30d;
    """

    with conn.cursor() as cur:
        cur.execute(sql, (warmup_start, end, start, end))
        rows = cur.rowcount
    conn.commit()
    return rows


def apply_staging_to_candles_month(conn, month_dates: list[date]) -> int:
    """
    UPDATE stock_candles_1m.rel_vol_30d from rel_vol_staging for one month.

    Joins on (symbol, computed trade_date, computed minute_of_day).
    One UPDATE per month keeps transactions manageable and allows
    progress tracking without locking the full 251M-row table.

    Returns rows updated.
    """
    if not month_dates:
        return 0

    first, last = month_dates[0], month_dates[-1]
    m_start = to_utc(et_at(first, MINUTE_START))
    m_end   = to_utc(et_at(last + timedelta(days=1), MINUTE_END))

    sql = f"""
    SET LOCAL work_mem = '1GB';

    UPDATE {SCHEMA}.stock_candles_1m m
       SET rel_vol_30d = s.rel_vol_30d
      FROM {SCHEMA}.rel_vol_staging s
     WHERE m.time    >= %s
       AND m.time     < %s
       AND m.symbol   = s.symbol
       AND DATE(m.time AT TIME ZONE 'America/New_York') = s.trade_date
       AND (EXTRACT(HOUR   FROM m.time AT TIME ZONE 'America/New_York')::int * 60
            + EXTRACT(MINUTE FROM m.time AT TIME ZONE 'America/New_York')::int
           ) = s.minute_of_day;
    """

    with conn.cursor() as cur:
        cur.execute(sql, (m_start, m_end))
        rows = cur.rowcount
    conn.commit()
    return rows


# ── Status report ─────────────────────────────────────────────────────────────

def print_status(conn, args) -> None:
    progress = load_progress()
    p1_done = set(progress.get('phase1_done', []))
    p2_done = set(progress.get('phase2_done', []))

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)
    all_days = get_all_trading_days(conn, start, end)
    cached   = get_cached_dates(conn)

    p1_needed = [d for d in all_days if d.isoformat() not in p1_done and d not in cached]
    p2_needed = [d for d in all_days if d.isoformat() not in p2_done]

    print(f"\n{'='*55}")
    print(f"  rel_vol_30d Backfill Status")
    print(f"{'='*55}")
    print(f"  Date range   : {start} to {end}")
    print(f"  Trading days : {len(all_days)}")
    print(f"")
    print(f"  Phase 1 (cache build):")
    print(f"    Already in cache DB : {len(cached)} dates")
    print(f"    Done via this script: {len(p1_done)} dates")
    print(f"    Still needed        : {len(p1_needed)} dates")
    if p1_needed:
        print(f"    First missing       : {p1_needed[0]}")
    print(f"")
    print(f"  Phase 2 (rel_vol_30d write):")
    print(f"    Done via this script: {len(p2_done)} dates")
    print(f"    Still needed        : {len(p2_needed)} dates")
    if p2_needed:
        print(f"    First missing       : {p2_needed[0]}")
    print(f"  Last update    : {progress.get('last_update', 'never')}")
    print(f"{'='*55}\n")
    conn.close()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Backfill rel_vol_30d for all historical trading days',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--start',   default='2021-01-01', help='Start date YYYY-MM-DD')
    parser.add_argument('--end',     default='2025-12-31', help='End date   YYYY-MM-DD')
    parser.add_argument('--phase',    type=int, choices=[1, 2],
                        help='Run only phase 1 (cache) or phase 2 (rel_vol write). Default: both.')
    parser.add_argument('--status',   action='store_true', help='Show progress and exit')
    parser.add_argument('--lookback', type=int, default=LOOKBACK_DAYS,
                        help=f'Rolling average window in trading days (default {LOOKBACK_DAYS})')
    parser.add_argument('--no-batch', action='store_true',
                        help='Phase 1: use per-day mode instead of monthly batch')
    parser.add_argument('--fast-p2', action='store_true',
                        help='Phase 2: use window-function staging approach instead of per-day loop')
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end   = date.fromisoformat(args.end)

    conn = connect_with_retry()

    if args.status:
        print_status(conn, args)
        return

    # Load all trading days and existing progress
    all_days = get_all_trading_days(conn, start, end)
    logger.info(f"Trading days in range [{start} – {end}]: {len(all_days)}")

    progress  = load_progress()
    p1_done   = set(progress.get('phase1_done', []))
    p2_done   = set(progress.get('phase2_done', []))
    cached_db = get_cached_dates(conn)

    run_phase1 = args.phase in (None, 1)
    run_phase2 = args.phase in (None, 2)

    # ── Phase 1: Build cache for missing dates ────────────────────────────────
    if run_phase1:
        p1_todo = [
            d for d in all_days
            if d.isoformat() not in p1_done and d not in cached_db
        ]
        logger.info(f"Phase 1: {len(p1_todo)} dates need cache build "
                    f"({len(cached_db)} already in DB, {len(p1_done)} done by script)")

        ensure_cache_table(conn)
        p1_t0 = time.time()

        if args.no_batch:
            # ── Per-day fallback ───────────────────────────────────────────
            for i, d in enumerate(p1_todo):
                t0 = time.time()
                try:
                    rows = build_cache_for_date(conn, d)
                    elapsed = time.time() - t0
                    p1_done.add(d.isoformat())
                    progress['phase1_done'] = sorted(p1_done)

                    if (i + 1) % 10 == 0 or i == 0:
                        elapsed_total = time.time() - p1_t0
                        rate = elapsed_total / (i + 1)
                        remaining = (len(p1_todo) - i - 1) * rate
                        logger.info(
                            f"  P1 {i+1}/{len(p1_todo)}  {d}  "
                            f"rows={rows:,}  {elapsed:.1f}s  ETA {remaining/60:.0f}m"
                        )
                        save_progress(progress)

                except Exception as e:
                    logger.error(f"  P1 ERROR on {d}: {e}")
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = connect_with_retry()
                    save_progress(progress)
                    continue

        else:
            # ── Batch mode (default): chunks of BATCH_DAYS trading days ────
            # Smaller chunks (vs full month) prevent OOM on large symbol universes
            BATCH_DAYS = 8
            batches = [p1_todo[i:i+BATCH_DAYS] for i in range(0, len(p1_todo), BATCH_DAYS)]
            logger.info(f"  Batch mode: {len(batches)} batches of up to {BATCH_DAYS} days")

            for bi, batch_dates in enumerate(batches):
                # Fresh connection each batch — clears PG memory state, avoids accumulation
                try:
                    conn.close()
                except Exception:
                    pass
                conn = connect_with_retry()

                t0 = time.time()
                label = f"{batch_dates[0]} to {batch_dates[-1]}"
                try:
                    rows = build_cache_month_batch(conn, batch_dates)
                    elapsed = time.time() - t0

                    for d in batch_dates:
                        p1_done.add(d.isoformat())
                    progress['phase1_done'] = sorted(p1_done)

                    elapsed_total = time.time() - p1_t0
                    rate = elapsed_total / (bi + 1)
                    remaining = (len(batches) - bi - 1) * rate
                    logger.info(
                        f"  P1 batch {bi+1}/{len(batches)}  {label}  "
                        f"({len(batch_dates)} days)  rows={rows:,}  "
                        f"{elapsed:.1f}s  ETA {remaining/60:.0f}m"
                    )
                    save_progress(progress)

                except Exception as e:
                    logger.error(f"  P1 ERROR on batch {label}: {e}")
                    # PG may be down — reconnect with retry before per-day fallback
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = connect_with_retry()
                    save_progress(progress)
                    logger.info("  Reconnected. Falling back to per-day mode for this batch...")
                    for d in batch_dates:
                        if d.isoformat() in p1_done:
                            continue
                        try:
                            rows = build_cache_for_date(conn, d)
                            p1_done.add(d.isoformat())
                            progress['phase1_done'] = sorted(p1_done)
                            save_progress(progress)
                        except Exception as e2:
                            logger.error(f"    Per-day fallback ERROR on {d}: {e2}")
                            conn.rollback()

        save_progress(progress)
        p1_total = time.time() - p1_t0
        logger.info(f"Phase 1 complete: {len(p1_todo)} dates in {p1_total/60:.1f}m")

    # ── Phase 2: Write rel_vol_30d into stock_candles_1m ─────────────────────
    if run_phase2:
        p2_todo = [d for d in all_days if d.isoformat() not in p2_done]
        logger.info(f"Phase 2: {len(p2_todo)} dates need rel_vol_30d written "
                    f"({len(p2_done)} already done by script)")

        p2_t0 = time.time()

        if args.fast_p2:
            # ── Fast mode: window function → staging table → monthly UPDATE ──

            # Group todo dates by month for UPDATE batching
            months: dict = {}
            for d in p2_todo:
                months.setdefault((d.year, d.month), []).append(d)
            month_keys = sorted(months.keys())

            # Step 1: build staging table in 6-month chunks (safe memory footprint)
            if p2_todo:
                logger.info(f"  Fast P2 step 1: building rel_vol_staging in 6-month chunks "
                             f"({p2_todo[0]} → {p2_todo[-1]})...")
                # Group todo dates into 6-month windows
                staging_chunks: list[tuple[date, date]] = []
                chunk_start = p2_todo[0]
                while chunk_start <= p2_todo[-1]:
                    # Advance 6 months
                    m = chunk_start.month + 5
                    y = chunk_start.year + (m - 1) // 12
                    m = (m - 1) % 12 + 1
                    # End of that month
                    import calendar
                    chunk_end = date(y, m, calendar.monthrange(y, m)[1])
                    chunk_end = min(chunk_end, p2_todo[-1])
                    staging_chunks.append((chunk_start, chunk_end))
                    chunk_start = chunk_end + timedelta(days=1)

                total_staging_rows = 0
                staging_ok = True
                for ci, (cs, ce) in enumerate(staging_chunks):
                    t0 = time.time()
                    try:
                        rows = build_rel_vol_staging(conn, cs, ce)
                        total_staging_rows += rows
                        logger.info(f"  Staging chunk {ci+1}/{len(staging_chunks)}  "
                                    f"{cs}→{ce}  rows={rows:,}  {time.time()-t0:.1f}s")
                    except Exception as e:
                        logger.error(f"  Staging chunk {ci+1} FAILED ({cs}→{ce}): {e}")
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        # Reconnect and continue
                        try:
                            conn = psycopg2.connect(DB_CONN)
                        except Exception as e2:
                            logger.error(f"  Reconnect failed: {e2}")
                            staging_ok = False
                            break
                logger.info(f"  Staging total: {total_staging_rows:,} rows")
                if not staging_ok:
                    logger.error("  Staging build failed — aborting fast P2")
                    return

            # Step 2: apply staging to stock_candles_1m, one month at a time
            logger.info(f"  Fast P2 step 2: applying to stock_candles_1m "
                         f"({len(month_keys)} months)...")
            for mi, ym in enumerate(month_keys):
                month_dates = months[ym]
                t0 = time.time()
                try:
                    rows = apply_staging_to_candles_month(conn, month_dates)
                    elapsed = time.time() - t0

                    for d in month_dates:
                        p2_done.add(d.isoformat())
                    progress['phase2_done'] = sorted(p2_done)

                    elapsed_total = time.time() - p2_t0
                    rate = elapsed_total / (mi + 1)
                    remaining = (len(month_keys) - mi - 1) * rate
                    logger.info(
                        f"  P2 month {mi+1}/{len(month_keys)}  "
                        f"{ym[0]}-{ym[1]:02d}  ({len(month_dates)} days)  "
                        f"rows={rows:,}  {elapsed:.1f}s  ETA {remaining/60:.0f}m"
                    )
                    save_progress(progress)

                except Exception as e:
                    logger.error(f"  P2 ERROR on month {ym}: {e}")
                    conn.rollback()
                    save_progress(progress)
                    continue

        else:
            # ── Per-day mode (original) ────────────────────────────────────
            for i, d in enumerate(p2_todo):
                t0 = time.time()
                try:
                    rows = backfill_rel_vol_for_date(conn, d)
                    elapsed = time.time() - t0
                    p2_done.add(d.isoformat())
                    progress['phase2_done'] = sorted(p2_done)

                    if (i + 1) % 10 == 0 or i == 0:
                        elapsed_total = time.time() - p2_t0
                        rate = elapsed_total / (i + 1)
                        remaining = (len(p2_todo) - i - 1) * rate
                        logger.info(
                            f"  P2 {i+1}/{len(p2_todo)}  {d}  "
                            f"rows={rows:,}  {elapsed:.1f}s  ETA {remaining/60:.0f}m"
                        )
                        save_progress(progress)

                except Exception as e:
                    logger.error(f"  P2 ERROR on {d}: {e}")
                    conn.rollback()
                    save_progress(progress)
                    continue

        save_progress(progress)
        p2_total = time.time() - p2_t0
        logger.info(f"Phase 2 complete: {len(p2_todo)} dates in {p2_total/60:.1f}m")

    conn.close()
    logger.info("Done.")


if __name__ == '__main__':
    main()
