"""
compress_and_cleanup.py — reclaim disk after the rel_vol backfill.

Run ONLY after Phase 2 backfill is fully complete (it touches the same tables and
enables compression, which fights concurrent writes). Idempotent + resumable:
compress_chunk skips already-compressed chunks, DROP uses IF EXISTS.

    python research/maintenance/compress_and_cleanup.py --confirm

Expected reclaim (from the 2026-05-29 audit, DB was 115 GB):
  1. Drop duplicate index on rel_vol_cum_cache .......... ~11 GB (zero risk; exact dup)
  2. TimescaleDB compression on candle hypertables ...... 64 GB -> ~5-8 GB
  3. Drop rel_vol_staging (temp table) .................. ~7.5 GB
  Net: ~115 GB -> ~40-50 GB.

Safety:
  - Refuses to run without --confirm.
  - Refuses to run if a backfill query is still active (checks pg_stat_activity).
  - Compression targets historical candle data that is done being written; a
    compression POLICY keeps future live chunks compressed after 7 days.
"""

from __future__ import annotations
import argparse
import sys
import time

import psycopg2

DB_CONN = 'postgresql://postgres:changeme123@localhost:5432/stockdata'

# Candle hypertables to compress (segment by symbol, order by time DESC).
# OHLCV numbers compress ~90-95%. scanner_results / materialized views excluded.
CANDLE_HYPERTABLES = [
    'stock_candles_1m',
    'stock_candles_1h',
    'stock_candles_1d',
    'stock_candles',
    'stock_snapshots',
]

# One of these two is an exact duplicate of the other on rel_vol_cum_cache
# (both: btree(symbol, minute_of_day, trade_date)). Drop this one.
DUPLICATE_INDEX = 'rel_vol_cum_cache_sym_min_date'


def db_size(cur) -> str:
    cur.execute("SELECT pg_size_pretty(pg_database_size('stockdata'))")
    return cur.fetchone()[0]


def backfill_active(cur) -> bool:
    cur.execute("""
        SELECT count(*) FROM pg_stat_activity
        WHERE datname='stockdata' AND state='active'
          AND (query ILIKE '%rel_vol_staging%' OR query ILIKE '%rel_vol_cum_cache%'
               OR query ILIKE '%stock_candles_1m m%')
          AND pid <> pg_backend_pid()
    """)
    return cur.fetchone()[0] > 0


def step_drop_dup_index(conn):
    with conn.cursor() as cur:
        # Look up via pg_class (returns no row if already dropped — idempotent;
        # a ::regclass cast would RAISE UndefinedTable instead of returning NULL).
        cur.execute("""
            SELECT pg_size_pretty(pg_relation_size(oid))
            FROM pg_class WHERE relname = %s
        """, (DUPLICATE_INDEX,))
        row = cur.fetchone()
        if row is None:
            print(f"  [idx] {DUPLICATE_INDEX} not found — skip")
            return
        print(f"  [idx] dropping duplicate index {DUPLICATE_INDEX} ({row[0]})...")
        cur.execute(f"DROP INDEX IF EXISTS {DUPLICATE_INDEX}")
    conn.commit()
    print("  [idx] done")


def step_compress(conn):
    for ht in CANDLE_HYPERTABLES:
        with conn.cursor() as cur:
            # Enable compression (idempotent — ignore "already" error).
            try:
                cur.execute(f"""
                    ALTER TABLE {ht} SET (
                        timescaledb.compress,
                        timescaledb.compress_segmentby = 'symbol',
                        timescaledb.compress_orderby = 'time DESC'
                    )
                """)
                conn.commit()
            except psycopg2.Error as e:
                conn.rollback()
                print(f"  [{ht}] compress settings: {str(e).strip().splitlines()[0]}")

            # Compress every uncompressed chunk.
            cur.execute("""
                SELECT format('%%I.%%I', chunk_schema, chunk_name)
                FROM timescaledb_information.chunks
                WHERE hypertable_name = %s AND NOT is_compressed
            """, (ht,))
            chunks = [r[0] for r in cur.fetchall()]
        if not chunks:
            print(f"  [{ht}] no uncompressed chunks — skip")
            continue
        print(f"  [{ht}] compressing {len(chunks)} chunks...")
        for i, ch in enumerate(chunks, 1):
            t0 = time.time()
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT compress_chunk(%s)", (ch,))
                    conn.commit()
                except psycopg2.Error as e:
                    conn.rollback()
                    print(f"    {ch}: {str(e).strip().splitlines()[0]}")
                    continue
            if i % 25 == 0 or i == len(chunks):
                print(f"    {ht} {i}/{len(chunks)} ({time.time()-t0:.1f}s last)")
        # Keep future (live) chunks compressed after 7 days.
        with conn.cursor() as cur:
            try:
                cur.execute("SELECT add_compression_policy(%s, INTERVAL '7 days')", (ht,))
                conn.commit()
                print(f"  [{ht}] compression policy added (7d)")
            except psycopg2.Error as e:
                conn.rollback()
                print(f"  [{ht}] policy: {str(e).strip().splitlines()[0]}")


def step_drop_staging(conn):
    with conn.cursor() as cur:
        print("  [staging] DROP TABLE IF EXISTS rel_vol_staging ...")
        cur.execute("DROP TABLE IF EXISTS rel_vol_staging")
    conn.commit()
    print("  [staging] done")


def main():
    ap = argparse.ArgumentParser(description='Compress candle hypertables + drop dead disk')
    ap.add_argument('--confirm', action='store_true', help='Required. Without it, dry-run only.')
    ap.add_argument('--skip-compress', action='store_true', help='Only drop dup index + staging')
    args = ap.parse_args()

    conn = psycopg2.connect(DB_CONN)
    with conn.cursor() as cur:
        before = db_size(cur)
        active = backfill_active(cur)
    print(f"DB size before: {before}")

    if active:
        print("ABORT: a backfill query is still ACTIVE on these tables. Wait for it to finish.")
        conn.close()
        sys.exit(1)

    if not args.confirm:
        print("\nDRY RUN (no --confirm). Would:")
        print(f"  1. DROP duplicate index {DUPLICATE_INDEX} (~11 GB)")
        if not args.skip_compress:
            print(f"  2. Enable + run compression on: {', '.join(CANDLE_HYPERTABLES)}")
        print("  3. DROP TABLE rel_vol_staging (~7.5 GB)")
        print("\nRe-run with --confirm to execute.")
        conn.close()
        return

    print("\n=== Step 1: drop duplicate index ===")
    step_drop_dup_index(conn)
    if not args.skip_compress:
        print("\n=== Step 2: compress candle hypertables ===")
        step_compress(conn)
    print("\n=== Step 3: drop staging table ===")
    step_drop_staging(conn)

    with conn.cursor() as cur:
        after = db_size(cur)
    print(f"\nDB size: {before} -> {after}")
    conn.close()


if __name__ == '__main__':
    main()
