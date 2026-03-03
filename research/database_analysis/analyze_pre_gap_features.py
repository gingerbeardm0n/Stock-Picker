#!/usr/bin/env python3
"""
Analyze minute-bar features immediately before each gap-run starts.

Gap-run definition (per symbol/day):
  - Consecutive green candles (close > open), minute-by-minute
  - Compute run gain = (end_close / start_open - 1) * 100
  - Keep runs with gain >= min_gain (default 5%)

For each run, record features from the minute immediately BEFORE the run starts.
Also record a few short-window features from the 5 minutes before the run.
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


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def et_at(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET_TZ)


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def fetch_day_minutes(conn, schema: str, d: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(d, 0, 0))
    end_utc = et_to_utc(et_at(d + timedelta(days=1), 0, 0))
    sql = f"""
    SELECT time, symbol, open, high, low, close, volume, trade_count, vwap, rel_vol_30d
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ORDER BY symbol, time;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(
            columns=[
                "time",
                "symbol",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "trade_count",
                "vwap",
                "rel_vol_30d",
            ]
        )
    df = pd.DataFrame(
        rows,
        columns=[
            "time",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_count",
            "vwap",
            "rel_vol_30d",
        ],
    )
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for col in ["open", "high", "low", "close", "volume", "trade_count", "vwap", "rel_vol_30d"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def find_green_runs(group: pd.DataFrame, min_gain: float) -> list[dict]:
    # group sorted by time
    runs = []
    times = group["time"].values
    opens = group["open"].values
    closes = group["close"].values

    run_start = None
    for i in range(len(group)):
        is_green = closes[i] > opens[i]
        if not is_green:
            run_start = None
            continue

        if run_start is None:
            run_start = i
        else:
            dt_minutes = int((times[i] - times[i - 1]) / pd.Timedelta(minutes=1))
            if dt_minutes != 1:
                run_start = i

        run_end = i
        start_open = opens[run_start]
        end_close = closes[run_end]
        if start_open and start_open > 0:
            gain = (end_close / start_open - 1.0) * 100.0
            if gain >= min_gain:
                runs.append(
                    {
                        "run_start_idx": run_start,
                        "run_end_idx": run_end,
                        "run_gain_pct": gain,
                        "run_minutes": run_end - run_start + 1,
                    }
                )
    return runs


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze pre-gap features")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--min-gain", type=float, default=5.0, help="Min run gain %")
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default database/audit_reports/pre_gap_features_<start>_<end>.csv)",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    output_path = args.output or os.path.join(
        "database",
        "audit_reports",
        f"pre_gap_features_{args.start}_{args.end}.csv",
    )

    conn = psycopg2.connect(DB_CONN)
    rows = []
    try:
        for d in daterange(start, end):
            df = fetch_day_minutes(conn, args.schema, d)
            if df.empty:
                continue

            for symbol, group in df.groupby("symbol", sort=False):
                group = group.sort_values("time").reset_index(drop=True)
                runs = find_green_runs(group, args.min_gain)
                if not runs:
                    continue

                for run in runs:
                    start_idx = run["run_start_idx"]
                    end_idx = run["run_end_idx"]
                    run_start_time = group.loc[start_idx, "time"]
                    run_end_time = group.loc[end_idx, "time"]

                    # Minute immediately before run starts
                    pre_idx = start_idx - 1
                    if pre_idx < 0:
                        continue

                    # Ensure it is consecutive minute
                    dt_minutes = int(
                        (group.loc[start_idx, "time"] - group.loc[pre_idx, "time"])
                        / pd.Timedelta(minutes=1)
                    )
                    if dt_minutes != 1:
                        continue

                    pre = group.loc[pre_idx]

                    # Short window features: last 5 minutes before run start (including pre)
                    window_start = max(0, start_idx - 5)
                    window = group.loc[window_start:pre_idx]
                    window_return = None
                    if not window.empty:
                        window_return = (
                            (window["close"].iloc[-1] / window["open"].iloc[0] - 1.0) * 100.0
                            if window["open"].iloc[0] > 0
                            else None
                        )
                    window_vol_sum = window["volume"].sum() if not window.empty else None
                    window_green_frac = (
                        (window["close"] > window["open"]).mean() if not window.empty else None
                    )

                    # Pre-minute derived metrics
                    pre_range = pre["high"] - pre["low"] if pd.notna(pre["high"]) and pd.notna(pre["low"]) else None
                    pre_body = pre["close"] - pre["open"] if pd.notna(pre["close"]) and pd.notna(pre["open"]) else None
                    pre_range_pct = (
                        (pre_range / pre["open"]) * 100.0
                        if pre_range is not None and pre["open"] and pre["open"] > 0
                        else None
                    )
                    pre_body_pct = (
                        (pre_body / pre["open"]) * 100.0
                        if pre_body is not None and pre["open"] and pre["open"] > 0
                        else None
                    )

                    rows.append(
                        {
                            "trade_date": d.isoformat(),
                            "symbol": symbol,
                            "run_start_time_et": run_start_time.tz_convert(ET_TZ).isoformat(),
                            "run_end_time_et": run_end_time.tz_convert(ET_TZ).isoformat(),
                            "run_minutes": run["run_minutes"],
                            "run_gain_pct": run["run_gain_pct"],
                            "pre_time_et": pre["time"].tz_convert(ET_TZ).isoformat(),
                            "pre_open": pre["open"],
                            "pre_high": pre["high"],
                            "pre_low": pre["low"],
                            "pre_close": pre["close"],
                            "pre_volume": pre["volume"],
                            "pre_trade_count": pre["trade_count"],
                            "pre_vwap": pre["vwap"],
                            "pre_rel_vol_30d": pre["rel_vol_30d"],
                            "pre_range_pct": pre_range_pct,
                            "pre_body_pct": pre_body_pct,
                            "window_5m_return_pct": window_return,
                            "window_5m_volume_sum": window_vol_sum,
                            "window_5m_green_frac": window_green_frac,
                        }
                    )
    finally:
        conn.close()

    out_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out_df.to_csv(output_path, index=False)
    print(f"Wrote {len(out_df)} rows to {output_path}")


if __name__ == "__main__":
    main()
