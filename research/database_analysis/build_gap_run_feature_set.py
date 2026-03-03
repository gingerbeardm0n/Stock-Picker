#!/usr/bin/env python3
"""
Build a feature set for gap-runs using only data BEFORE each run starts.

Gap-run definition:
  - Consecutive green candles (close > open), minute-by-minute
  - Run gain = (end_close / start_open - 1) * 100
  - Keep runs with gain >= min_gain (default 5%)

Features:
  - Premarket (4-8am ET) from 1h bars
  - Minute aggregates from earliest available minute to pre-run minute
  - Pre-run minute stats (the minute immediately before the run)
  - Last-5-minute window stats before the run
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


def fetch_premarket_hours(conn, schema: str, d: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(d, 4, 0))
    end_utc = et_to_utc(et_at(d, 8, 0))
    sql = f"""
    SELECT time, symbol, open, high, low, close, volume
    FROM {schema}.stock_candles_1h
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ORDER BY symbol, time;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["time", "symbol", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["time", "symbol", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def find_green_runs(group: pd.DataFrame, min_gain: float) -> list[dict]:
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
    parser = argparse.ArgumentParser(description="Build gap-run feature set")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--min-gain", type=float, default=5.0, help="Min run gain %")
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default database/audit_reports/gap_run_features_<start>_<end>.csv)",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    output_path = args.output or os.path.join(
        "database",
        "audit_reports",
        f"gap_run_features_{args.start}_{args.end}.csv",
    )

    conn = psycopg2.connect(DB_CONN)
    rows = []
    try:
        for d in daterange(start, end):
            mins = fetch_day_minutes(conn, args.schema, d)
            if mins.empty:
                continue
            prem = fetch_premarket_hours(conn, args.schema, d)

            # premarket aggregates per symbol
            pre_agg = {}
            if not prem.empty:
                for symbol, g in prem.groupby("symbol", sort=False):
                    g = g.sort_values("time")
                    pre_open = g["open"].iloc[0]
                    pre_close = g["close"].iloc[-1]
                    pre_high = g["high"].max()
                    pre_low = g["low"].min()
                    pre_vol = g["volume"].sum()
                    pre_trend_pct = (
                        (pre_close / pre_open - 1.0) * 100.0 if pre_open and pre_open > 0 else None
                    )
                    pre_range_pct = (
                        (pre_high - pre_low) / pre_open * 100.0
                        if pre_open and pre_open > 0
                        else None
                    )
                    pre_agg[symbol] = {
                        "pre_vol_4_8": pre_vol,
                        "pre_trend_pct": pre_trend_pct,
                        "pre_range_pct": pre_range_pct,
                    }

            for symbol, group in mins.groupby("symbol", sort=False):
                group = group.sort_values("time").reset_index(drop=True)
                runs = find_green_runs(group, args.min_gain)
                if not runs:
                    continue

                for run in runs:
                    start_idx = run["run_start_idx"]
                    end_idx = run["run_end_idx"]
                    run_start_time = group.loc[start_idx, "time"]
                    run_end_time = group.loc[end_idx, "time"]

                    pre_idx = start_idx - 1
                    if pre_idx < 0:
                        continue

                    dt_minutes = int(
                        (group.loc[start_idx, "time"] - group.loc[pre_idx, "time"])
                        / pd.Timedelta(minutes=1)
                    )
                    if dt_minutes != 1:
                        continue

                    pre = group.loc[pre_idx]
                    earliest = group.loc[0]
                    pre_open = earliest["open"]
                    pre_close = pre["close"]

                    # From earliest minute to pre-minute aggregates
                    pre_window = group.loc[0:pre_idx]
                    pre_return_pct = (
                        (pre_close / pre_open - 1.0) * 100.0
                        if pre_open and pre_open > 0
                        else None
                    )
                    pre_range_pct = (
                        (pre_window["high"].max() - pre_window["low"].min()) / pre_open * 100.0
                        if pre_open and pre_open > 0
                        else None
                    )
                    pre_vol_sum = pre_window["volume"].sum()
                    pre_green_frac = (pre_window["close"] > pre_window["open"]).mean()

                    # Last-5-minute window before run
                    last5_start = max(0, start_idx - 5)
                    last5 = group.loc[last5_start:pre_idx]
                    last5_return_pct = None
                    if not last5.empty:
                        o0 = last5["open"].iloc[0]
                        c1 = last5["close"].iloc[-1]
                        last5_return_pct = (
                            (c1 / o0 - 1.0) * 100.0 if o0 and o0 > 0 else None
                        )
                    last5_vol_sum = last5["volume"].sum() if not last5.empty else None
                    last5_green_frac = (
                        (last5["close"] > last5["open"]).mean() if not last5.empty else None
                    )
                    last5_range_pct = (
                        (last5["high"].max() - last5["low"].min()) / last5["open"].iloc[0] * 100.0
                        if not last5.empty and last5["open"].iloc[0] and last5["open"].iloc[0] > 0
                        else None
                    )

                    # Pre-minute candle stats
                    pre_range = pre["high"] - pre["low"] if pd.notna(pre["high"]) and pd.notna(pre["low"]) else None
                    pre_body = pre["close"] - pre["open"] if pd.notna(pre["close"]) and pd.notna(pre["open"]) else None
                    pre_range_pct_candle = (
                        (pre_range / pre["open"]) * 100.0
                        if pre_range is not None and pre["open"] and pre["open"] > 0
                        else None
                    )
                    pre_body_pct = (
                        (pre_body / pre["open"]) * 100.0
                        if pre_body is not None and pre["open"] and pre["open"] > 0
                        else None
                    )

                    premeta = pre_agg.get(symbol, {})

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
                            "pre_range_pct": pre_range_pct_candle,
                            "pre_body_pct": pre_body_pct,
                            "pre_return_pct": pre_return_pct,
                            "pre_range_total_pct": pre_range_pct,
                            "pre_volume_sum": pre_vol_sum,
                            "pre_green_frac": pre_green_frac,
                            "last5_return_pct": last5_return_pct,
                            "last5_volume_sum": last5_vol_sum,
                            "last5_green_frac": last5_green_frac,
                            "last5_range_pct": last5_range_pct,
                            "pre_vol_4_8": premeta.get("pre_vol_4_8"),
                            "pre_trend_pct": premeta.get("pre_trend_pct"),
                            "pre_range_pct_4_8": premeta.get("pre_range_pct"),
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
