"""
db_fingerprint.py — make sealed backtests reproducible by fingerprinting the DB
slice they score on.

WHY: VWAP trial 173's sealed-2025 result (+$2,669/90% WR) does NOT reproduce on
today's DB (+$19/40%). The config + engine code are unchanged — the DATABASE
mutated (backfill / repopulation) after the sealed run. A sealed test is only
valid if the data it scored on is frozen. This tool takes a lightweight,
drift-sensitive fingerprint of the tables a strategy reads, per trade-date, so:

  1. Before sealing a test  → snapshot the fingerprint (commit the JSON).
  2. Re-running it later     → `--compare` flags exactly which dates/tables drifted.
  3. Any "stale result" debate → answered by data, not guesswork.

The fingerprint per (table, date) is a cheap aggregate, NOT a full row hash:
row count + sum(volume) + sum(close) (or sum(cum_total) / row count for the
cache / news). Any added, removed, or changed row in that date shifts the tuple.
Cheap enough to run over a full year in seconds; sensitive enough to catch
backfill repopulation.

Usage:
    python db_fingerprint.py --start 2025-01-01 --end 2025-12-31 \
        --out research/analysis/outputs/fp_2025.json
    python db_fingerprint.py --start 2025-01-01 --end 2025-12-31 \
        --compare research/analysis/outputs/fp_2025.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
load_dotenv(os.path.join(REPO_ROOT, '.env.paper'))

DB_DSN = os.getenv('DB_DSN') or os.getenv('OPTUNA_STORAGE')
if not DB_DSN:
    sys.exit("Set DB_DSN (postgresql://user:pass@host:5432/stockdata) in env or .env.paper")

# Per-table, date-bucketed fingerprint queries. Each returns rows of
# (bucket_date, *aggregates). The aggregate tuple is what must stay constant for
# a sealed result to reproduce; any drift shifts it. round()s keep float noise out.
TABLE_QUERIES = {
    'stock_candles_1m': """
        SELECT time::date AS d, COUNT(*),
               COALESCE(SUM(volume), 0),
               ROUND(COALESCE(SUM(close), 0)::numeric, 2)
        FROM stock_candles_1m
        WHERE time::date BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1
    """,
    'stock_candles_1d': """
        SELECT time::date AS d, COUNT(*),
               COALESCE(SUM(volume), 0),
               ROUND(COALESCE(SUM(close), 0)::numeric, 2)
        FROM stock_candles_1d
        WHERE time::date BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1
    """,
    'rel_vol_cum_cache': """
        SELECT trade_date AS d, COUNT(*),
               ROUND(COALESCE(SUM(cum_total), 0)::numeric, 0)
        FROM rel_vol_cum_cache
        WHERE trade_date BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1
    """,
    'stock_news': """
        SELECT created_at::date AS d, COUNT(*),
               COUNT(*) FILTER (WHERE news_tier IS NOT NULL AND news_tier <> 'none')
        FROM stock_news
        WHERE created_at::date BETWEEN %s AND %s
        GROUP BY 1 ORDER BY 1
    """,
}


def fingerprint(start: str, end: str) -> dict:
    """Return {table: {YYYY-MM-DD: [agg, ...]}} for the date range."""
    conn = psycopg2.connect(DB_DSN)
    out: dict[str, dict] = {}
    try:
        for table, sql in TABLE_QUERIES.items():
            try:
                with conn.cursor() as cur:
                    cur.execute(sql, (start, end))
                    rows = cur.fetchall()
                # row[0] = date; rest = aggregates (as str for stable JSON compare)
                out[table] = {
                    str(r[0]): [str(x) for x in r[1:]] for r in rows
                }
            except Exception as e:  # noqa: BLE001 — one missing table shouldn't kill the run
                conn.rollback()
                out[table] = {'_error': str(e)}
    finally:
        conn.close()
    return {
        'as_of': date.today().isoformat(),
        'start': start,
        'end': end,
        'tables': out,
    }


def compare(old: dict, new: dict) -> int:
    """Print per-table drift between two manifests. Returns drift count."""
    old_t = old.get('tables', {})
    new_t = new.get('tables', {})
    total_drift = 0
    print(f"Comparing  old as_of={old.get('as_of')}  vs  new as_of={new.get('as_of')}")
    print("=" * 64)
    for table in sorted(set(old_t) | set(new_t)):
        o = old_t.get(table, {})
        n = new_t.get(table, {})
        dates = sorted(set(o) | set(n))
        changed = added = removed = 0
        samples = []
        for d in dates:
            if d.startswith('_'):
                continue
            if d not in o:
                added += 1
            elif d not in n:
                removed += 1
            elif o[d] != n[d]:
                changed += 1
                if len(samples) < 3:
                    samples.append(f"{d}: {o[d]} -> {n[d]}")
        drift = changed + added + removed
        total_drift += drift
        status = "OK" if drift == 0 else f"DRIFT {drift}"
        print(f"  {table:20s} {status}"
              + (f"  (changed={changed} added={added} removed={removed})" if drift else ""))
        for s in samples:
            print(f"      {s}")
    print("=" * 64)
    print(f"TOTAL DRIFT: {total_drift} "
          + ("— data is REPRODUCIBLE for this range" if total_drift == 0
             else "— sealed results on this range are NOT reproducible"))
    return total_drift


def main() -> None:
    ap = argparse.ArgumentParser(description="Fingerprint the DB slice a sealed backtest scores on.")
    ap.add_argument('--start', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='YYYY-MM-DD')
    ap.add_argument('--out', help='write the manifest JSON here')
    ap.add_argument('--compare', help='compare current DB against this saved manifest')
    args = ap.parse_args()

    current = fingerprint(args.start, args.end)

    if args.compare:
        with open(args.compare) as f:
            old = json.load(f)
        drift = compare(old, current)
        sys.exit(1 if drift else 0)

    n = sum(len([k for k in v if not k.startswith('_')]) for v in current['tables'].values())
    print(f"Fingerprinted {args.start}..{args.end}: {n} table-date buckets across "
          f"{len(current['tables'])} tables.")
    for table, buckets in current['tables'].items():
        real = {k: v for k, v in buckets.items() if not k.startswith('_')}
        if '_error' in buckets:
            print(f"  {table:20s} ERROR: {buckets['_error']}")
        else:
            print(f"  {table:20s} {len(real):4d} dates")

    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, 'w') as f:
            json.dump(current, f, separators=(',', ':'))
        print(f"Wrote {args.out}")
    else:
        print("(no --out: not saved)")


if __name__ == '__main__':
    main()
