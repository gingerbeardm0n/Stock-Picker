#!/usr/bin/env python3
"""
Sweep day-gain and rel-vol thresholds across the full universe.

For each day in range:
  - compute per-symbol pillar values at first minute >= 9:29 ET
  - apply thresholds to get candidate count
  - compute recall on top gappers (from top_gappers CSV)

Outputs a CSV with per-threshold metrics.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv(".env")

DB_CONN = os.getenv(
    "TIMESCALE_CONNECTION_STRING",
    "postgresql://postgres:changeme123@localhost:5432/stockdata",
)

ET_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def et_at(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET_TZ)


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def load_prev_close_map(conn, schema: str, start: date, end: date) -> dict[tuple[date, str], float]:
    start_dt = start - timedelta(days=1)
    start_utc = et_to_utc(et_at(start_dt, 0, 0))
    end_utc = et_to_utc(et_at(end + timedelta(days=1), 0, 0))
    sql = f"""
    WITH d AS (
        SELECT
            symbol,
            (time AT TIME ZONE 'America/New_York')::date AS trade_date,
            close
        FROM {schema}.stock_candles_1d
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ),
    x AS (
        SELECT
            symbol,
            trade_date,
            close,
            LAG(close) OVER (PARTITION BY symbol ORDER BY trade_date) AS prev_close
        FROM d
    )
    SELECT trade_date, symbol, prev_close
    FROM x;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    return {(r[0], r[1]): float(r[2]) for r in rows if r[2] is not None}


def load_universe_929plus(conn, schema: str, start: date, end: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(start, 0, 0))
    end_utc = et_to_utc(et_at(end + timedelta(days=1), 0, 0))
    t929_start = et_to_utc(et_at(start, 9, 29))
    t929_end = end_utc

    sql = f"""
    WITH m AS (
        SELECT
            time,
            symbol,
            close,
            rel_vol_30d,
            (time AT TIME ZONE 'America/New_York')::date AS trade_date
        FROM {schema}.stock_candles_1m
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
          AND time >= %s::timestamptz
    ),
    first_929 AS (
        SELECT DISTINCT ON (trade_date, symbol)
            trade_date,
            symbol,
            close AS price_929plus,
            rel_vol_30d AS rel_vol_30d_929plus
        FROM m
        ORDER BY trade_date, symbol, time ASC
    )
    SELECT * FROM first_929;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc, t929_start))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["trade_date", "symbol", "price_929plus", "rel_vol_30d_929plus"]
        )
    df = pd.DataFrame(rows, columns=["trade_date", "symbol", "price_929plus", "rel_vol_30d_929plus"])
    return df


def load_float_map(conn, schema: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol, float_shares FROM {schema}.stock_fundamentals")
        return {row[0]: row[1] for row in cur.fetchall()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep thresholds over full universe")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--top-gappers", required=True, help="Path to top_gappers CSV")
    parser.add_argument(
        "--day-gain-thresholds",
        default="2,3,5,7,10",
        help="Comma-separated day gain thresholds (%)",
    )
    parser.add_argument(
        "--rel-vol-thresholds",
        default="1.5,2,3,5",
        help="Comma-separated rel vol thresholds (x)",
    )
    parser.add_argument(
        "--output",
        default="database/audit_reports/universe_threshold_sweep.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    day_thresholds = [float(x) for x in args.day_gain_thresholds.split(",")]
    rel_thresholds = [float(x) for x in args.rel_vol_thresholds.split(",")]

    conn = psycopg2.connect(DB_CONN)
    try:
        prev_close_map = load_prev_close_map(conn, args.schema, start, end)
        float_map = load_float_map(conn, args.schema)
        universe = load_universe_929plus(conn, args.schema, start, end)
    finally:
        conn.close()

    if universe.empty:
        raise SystemExit("No universe data found for 9:29+")

    universe["trade_date"] = pd.to_datetime(universe["trade_date"]).dt.date

    # Add day gain and float info
    # Normalize numeric types
    universe["price_929plus"] = universe["price_929plus"].astype(float)

    def compute_day_gain(row):
        prev = prev_close_map.get((row["trade_date"], row["symbol"]))
        if prev is None or row["price_929plus"] is None:
            return None
        return (row["price_929plus"] / float(prev) - 1.0) * 100.0

    universe["day_gain_pct_929plus"] = universe.apply(compute_day_gain, axis=1)
    universe["float_lt_20m"] = universe["symbol"].apply(
        lambda s: (float_map.get(s) is not None and float_map.get(s) < 20_000_000)
    )

    # Load top gappers for recall
    gappers = pd.read_csv(args.top_gappers)
    gappers["trade_date"] = pd.to_datetime(gappers["trade_date"]).dt.date
    gapper_sets = (
        gappers.groupby("trade_date")["symbol"].apply(set).to_dict()
    )

    rows = []
    for day_t in day_thresholds:
        for rel_t in rel_thresholds:
            # candidates across full universe
            day_pass = universe["day_gain_pct_929plus"].fillna(-1e9) >= day_t
            rel_pass = universe["rel_vol_30d_929plus"].fillna(-1e9) >= rel_t
            float_pass = universe["float_lt_20m"].fillna(False).astype(bool)
            cand = universe[day_pass & rel_pass & float_pass]

            # avg candidates per day
            cand_per_day = cand.groupby("trade_date")["symbol"].nunique()
            avg_cand = cand_per_day.mean() if not cand_per_day.empty else 0.0

            # recall on top gappers
            recalls = []
            for d, top_set in gapper_sets.items():
                day_cand = set(cand[cand["trade_date"] == d]["symbol"])
                if not top_set:
                    continue
                recalls.append(len(day_cand & top_set) / len(top_set))
            avg_recall = (sum(recalls) / len(recalls)) * 100.0 if recalls else 0.0

            rows.append(
                {
                    "day_gain_threshold": day_t,
                    "rel_vol_threshold": rel_t,
                    "avg_candidates_per_day": avg_cand,
                    "avg_recall_top5_pct": avg_recall,
                }
            )

    out_df = pd.DataFrame(rows).sort_values(
        ["avg_recall_top5_pct", "avg_candidates_per_day"], ascending=False
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
