#!/usr/bin/env python3
"""
Generate monthly top-100 gap-run symbol lists.

For each month with minute data:
  - scan all 1m candles in that month
  - find all gap-runs, defined as consecutive green candles with
    run_gain_pct >= min_gain
  - write two CSVs:
      * top 100 symbols by max run gain in the month
      * top 100 symbols by count of qualifying gap-runs in the month
"""

from __future__ import annotations

import argparse
import os
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


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def next_month(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def parse_month(value: str) -> date:
    return datetime.strptime(value, "%Y-%m").date().replace(day=1)


def et_at(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET_TZ)


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def list_available_months(conn, schema: str) -> list[date]:
    sql = f"""
    SELECT DISTINCT date_trunc('month', (time AT TIME ZONE 'America/New_York')::date)::date AS month_start
    FROM {schema}.stock_candles_1m
    ORDER BY month_start;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return [row[0] for row in cur.fetchall()]


def fetch_month_minutes(conn, schema: str, start: date, end: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(start, 0, 0))
    end_utc = et_to_utc(et_at(end, 0, 0))
    sql = f"""
    SELECT time, symbol, open, close
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ORDER BY symbol, time;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["time", "symbol", "open", "close", "trade_date"])
    df = pd.DataFrame(rows, columns=["time", "symbol", "open", "close"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["trade_date"] = df["time"].dt.tz_convert(ET_TZ).dt.date
    return df


def find_gap_runs(group: pd.DataFrame, min_gain: float) -> list[float]:
    runs: list[float] = []
    times = group["time"].values
    opens = group["open"].values
    closes = group["close"].values

    run_start = None
    for i in range(len(group)):
        if not (closes[i] > opens[i]):
            run_start = None
            continue

        if run_start is None:
            run_start = i
        else:
            dt_minutes = int((times[i] - times[i - 1]) / pd.Timedelta(minutes=1))
            if dt_minutes != 1:
                run_start = i

        start_open = opens[run_start]
        end_close = closes[i]
        if start_open and start_open > 0:
            gain = (end_close / start_open - 1.0) * 100.0
            if gain >= min_gain:
                runs.append(gain)
    return runs


def build_month_lists(df: pd.DataFrame, min_gain: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    gap_rows: list[tuple[str, float]] = []

    if df.empty:
        empty_max = pd.DataFrame(columns=["symbol", "max_run_gain_pct"])
        empty_count = pd.DataFrame(columns=["symbol", "gaprun_count"])
        return empty_max, empty_count

    for (_, symbol), group in df.groupby(["trade_date", "symbol"], sort=False):
        group = group.sort_values("time").reset_index(drop=True)
        gains = find_gap_runs(group, min_gain=min_gain)
        if not gains:
            continue
        for gain in gains:
            gap_rows.append((symbol, gain))

    if not gap_rows:
        empty_max = pd.DataFrame(columns=["symbol", "max_run_gain_pct"])
        empty_count = pd.DataFrame(columns=["symbol", "gaprun_count"])
        return empty_max, empty_count

    runs_df = pd.DataFrame(gap_rows, columns=["symbol", "run_gain_pct"])

    top_by_max = (
        runs_df.groupby("symbol", as_index=False)["run_gain_pct"]
        .max()
        .rename(columns={"run_gain_pct": "max_run_gain_pct"})
        .sort_values(["max_run_gain_pct", "symbol"], ascending=[False, True])
        .head(100)
    )

    top_by_count = (
        runs_df.groupby("symbol", as_index=False)
        .size()
        .rename(columns={"size": "gaprun_count"})
        .sort_values(["gaprun_count", "symbol"], ascending=[False, True])
        .head(100)
    )

    return top_by_max, top_by_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate monthly top-100 gap-run lists")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--min-gain", type=float, default=5.0, help="Minimum run gain percent")
    parser.add_argument("--month", help="Single month to process, format YYYY-MM")
    parser.add_argument("--output-dir", default="database/audit_reports/monthly_gaprun_lists", help="Output directory")
    args = parser.parse_args()

    conn = psycopg2.connect(DB_CONN)
    try:
        if args.month:
            months = [parse_month(args.month)]
        else:
            months = list_available_months(conn, args.schema)

        os.makedirs(args.output_dir, exist_ok=True)

        manifest_rows: list[dict] = []
        for start in months:
            end = next_month(start)
            month_key = start.strftime("%Y-%m")
            df = fetch_month_minutes(conn, args.schema, start, end)
            top_by_max, top_by_count = build_month_lists(df, min_gain=args.min_gain)

            max_path = os.path.join(args.output_dir, f"top_100_gaprun_symbols_by_max_gain_{month_key}.csv")
            count_path = os.path.join(args.output_dir, f"top_100_gaprun_symbols_by_count_{month_key}.csv")

            top_by_max.to_csv(max_path, index=False)
            top_by_count.to_csv(count_path, index=False)

            manifest_rows.append(
                {
                    "month": month_key,
                    "rows_scanned": len(df),
                    "top_by_max_count": len(top_by_max),
                    "top_by_count_count": len(top_by_count),
                    "top_by_max_path": max_path,
                    "top_by_count_path": count_path,
                }
            )

            print(f"{month_key}: wrote {max_path} and {count_path}")

        manifest = pd.DataFrame(manifest_rows)
        manifest_path = os.path.join(args.output_dir, "monthly_gaprun_manifest.csv")
        manifest.to_csv(manifest_path, index=False)
        print(f"manifest: {manifest_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
