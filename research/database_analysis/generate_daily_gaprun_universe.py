#!/usr/bin/env python3
"""
Generate daily top-N gap-run symbol lists.

For each trading day in the date range, scans 1-minute candles from
9:30am–11:00am ET and finds symbols that had the strongest consecutive
green-candle "gap-runs" (cumulative gain >= min_gain, default 5%).

Outputs two CSVs:
  analysis/daily_gaprun_universe.csv  — full ranked data per day
  analysis/daily_gaprun_symbols.csv   — optuna-ready (date,symbol) two-column

Usage:
  python database/generate_daily_gaprun_universe.py
  python database/generate_daily_gaprun_universe.py --start 2025-01-02 --end 2025-06-30
  python database/generate_daily_gaprun_universe.py --top-n 25 --min-gain 10.0
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

DEFAULT_START = date(2025, 1, 2)
DEFAULT_END = date(2026, 1, 31)
DEFAULT_TOP_N = 50
DEFAULT_MIN_GAIN = 5.0
WINDOW_START_HOUR, WINDOW_START_MIN = 9, 30
WINDOW_END_HOUR, WINDOW_END_MIN = 11, 0


def et_at(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET_TZ)


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Return (chunk_start, chunk_end) pairs covering [start, end] in monthly increments."""
    chunks = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        if cur.month == 12:
            next_m = date(cur.year + 1, 1, 1)
        else:
            next_m = date(cur.year, cur.month + 1, 1)
        chunk_end = min(next_m - timedelta(days=1), end)
        chunks.append((max(cur, start), chunk_end))
        cur = next_m
    return chunks


def fetch_window_minutes(conn, schema: str, start: date, end: date) -> pd.DataFrame:
    """
    Fetch all 1-minute candles in the 9:30am-11:00am ET window
    for every trading day in [start, end] chunked by month to avoid OOM.
    """
    sql = f"""
    SELECT time, symbol, open, close
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz
      AND time < %s::timestamptz
      AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') * 60
          + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')
          >= {WINDOW_START_HOUR * 60 + WINDOW_START_MIN}
      AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') * 60
          + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')
          < {WINDOW_END_HOUR * 60 + WINDOW_END_MIN}
    ORDER BY symbol, time;
    """
    chunks = month_chunks(start, end)
    all_dfs: list[pd.DataFrame] = []
    for chunk_start, chunk_end in chunks:
        start_utc = et_to_utc(et_at(chunk_start, WINDOW_START_HOUR, WINDOW_START_MIN))
        end_utc = et_to_utc(et_at(chunk_end + timedelta(days=1), WINDOW_END_HOUR, WINDOW_END_MIN))
        print(f"  Querying {schema}.stock_candles_1m "
              f"{chunk_start} to {chunk_end} (9:30–11:00am ET)...", flush=True)
        with conn.cursor() as cur:
            cur.execute(sql, (start_utc, end_utc))
            rows = cur.fetchall()
        if not rows:
            continue
        df = pd.DataFrame(rows, columns=["time", "symbol", "open", "close"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["open"] = pd.to_numeric(df["open"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["trade_date"] = df["time"].dt.tz_convert(ET_TZ).dt.date
        all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame(columns=["time", "symbol", "open", "close", "trade_date"])
    return pd.concat(all_dfs, ignore_index=True)


def find_gap_runs(group: pd.DataFrame, min_gain: float) -> list[float]:
    """
    Find all qualifying gap-runs in a sorted sequence of 1-minute candles.

    A gap-run is a streak of consecutive green candles (close > open) where:
      - Each candle is exactly 1 minute after the previous (no time gaps)
      - The cumulative gain from the streak's first open to the current close >= min_gain

    Returns a list of the qualifying gain values (one per qualifying candle in a run).
    Verbatim copy from database/generate_monthly_gaprun_top100_lists.py.
    """
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


def build_daily_lists(df: pd.DataFrame, min_gain: float, top_n: int) -> pd.DataFrame:
    """
    For each (trade_date, symbol) group, compute gap-run stats,
    then rank symbols within each day by max_run_gain_pct DESC.
    Returns a DataFrame with columns:
      date, symbol, rank, max_run_gain_pct, gaprun_count
    Only includes the top_n symbols per day.
    """
    if df.empty:
        return pd.DataFrame(columns=["date", "symbol", "rank", "max_run_gain_pct", "gaprun_count"])

    rows: list[dict] = []
    grouped = df.groupby(["trade_date", "symbol"], sort=False)

    for (trade_date, symbol), group in grouped:
        group = group.sort_values("time").reset_index(drop=True)
        gains = find_gap_runs(group, min_gain=min_gain)
        if not gains:
            continue
        rows.append({
            "date": trade_date,
            "symbol": symbol,
            "max_run_gain_pct": round(max(gains), 2),
            "gaprun_count": len(gains),
        })

    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "rank", "max_run_gain_pct", "gaprun_count"])

    result = pd.DataFrame(rows)

    # Sort within each day: max gain DESC, then count DESC, then symbol ASC
    result = result.sort_values(
        ["date", "max_run_gain_pct", "gaprun_count", "symbol"],
        ascending=[True, False, False, True],
    ).reset_index(drop=True)

    # Assign rank within each day and keep top_n
    result["rank"] = result.groupby("date").cumcount() + 1
    result = result[result["rank"] <= top_n].copy()

    return result[["date", "symbol", "rank", "max_run_gain_pct", "gaprun_count"]]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate daily top-N gap-run symbol lists (9:30am–11am ET)"
    )
    parser.add_argument("--start", default=DEFAULT_START.isoformat(),
                        help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end", default=DEFAULT_END.isoformat(),
                        help=f"End date YYYY-MM-DD inclusive (default: {DEFAULT_END})")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help=f"Max symbols to keep per day (default: {DEFAULT_TOP_N})")
    parser.add_argument("--min-gain", type=float, default=DEFAULT_MIN_GAIN,
                        help=f"Minimum gap-run gain %% (default: {DEFAULT_MIN_GAIN})")
    parser.add_argument("--output-dir", default="analysis",
                        help="Output directory (default: analysis/)")
    parser.add_argument("--schema", default="public",
                        help="DB schema (default: public)")
    args = parser.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    print("=" * 60)
    print("  GENERATE DAILY GAP-RUN UNIVERSE")
    print("=" * 60)
    print(f"  Date range : {start} to {end}")
    print(f"  Window     : 9:30am – 11:00am ET")
    print(f"  Min gain   : {args.min_gain}%")
    print(f"  Top N/day  : {args.top_n}")
    print(f"  Output dir : {args.output_dir}/")
    print()

    conn = psycopg2.connect(DB_CONN)
    try:
        df = fetch_window_minutes(conn, args.schema, start, end)
    finally:
        conn.close()

    total_bars = len(df)
    total_days = df["trade_date"].nunique() if not df.empty else 0
    total_syms = df["symbol"].nunique() if not df.empty else 0
    print(f"  Fetched {total_bars:,} 1-minute bars across "
          f"{total_days} trading days and {total_syms} symbols")
    print()

    print("  Building daily gap-run rankings...")
    daily = build_daily_lists(df, min_gain=args.min_gain, top_n=args.top_n)
    del df  # free memory

    if daily.empty:
        print("  WARNING: No qualifying gap-runs found. Check date range and data.")
        return

    # --- Stats summary ---
    dates_with_data = daily["date"].nunique()
    total_dates = (end - start).days + 1  # approx calendar days
    print(f"  Trading days with qualifying gap-runs: {dates_with_data}")
    avg_per_day = len(daily) / dates_with_data
    print(f"  Total date-symbol rows: {len(daily):,} (avg {avg_per_day:.1f}/day)")
    print(f"  Unique symbols: {daily['symbol'].nunique():,}")
    print()

    # Per-month summary
    daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M")
    monthly_summary = (
        daily.groupby("month")
        .agg(trading_days=("date", "nunique"), symbols=("symbol", "nunique"), rows=("symbol", "count"))
        .reset_index()
    )
    print("  Per-month breakdown:")
    for _, row in monthly_summary.iterrows():
        print(f"    {row['month']}: {row['trading_days']} days, "
              f"{row['symbols']} unique symbols, {row['rows']} rows")
    daily = daily.drop(columns=["month"])
    print()

    # --- Write outputs ---
    os.makedirs(args.output_dir, exist_ok=True)

    universe_path = os.path.join(args.output_dir, "daily_gaprun_universe.csv")
    daily.to_csv(universe_path, index=False)
    print(f"  Written: {universe_path}")

    symbols_path = os.path.join(args.output_dir, "daily_gaprun_symbols.csv")
    daily[["date", "symbol"]].to_csv(symbols_path, index=False)
    print(f"  Written: {symbols_path}  (optuna-ready date,symbol format)")

    # --- Spot-check: show top 5 symbols on the first date with data ---
    first_date = daily["date"].min()
    sample = daily[daily["date"] == first_date].head(5)
    print(f"\n  Sample — top 5 symbols on {first_date}:")
    for _, row in sample.iterrows():
        print(f"    #{int(row['rank']):2d}  {row['symbol']:<8s}  "
              f"max_gain={row['max_run_gain_pct']:.1f}%  "
              f"runs={int(row['gaprun_count'])}")

    print(f"  (Note: trading days with 0 qualifying gap-runs are excluded from output)")

    print("\n  Done.")


if __name__ == "__main__":
    main()
