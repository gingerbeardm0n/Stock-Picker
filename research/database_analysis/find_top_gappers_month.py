#!/usr/bin/env python3
"""
Find top N gappers per day over a date range and record pillar values.

Gapper definition (per symbol/day):
  - Use ALL minute data for the ET day.
  - Find the maximum % gain over any *consecutive green-candle run*.
    A green candle means close > open.
    The run must be consecutive minutes (time diff = 1 minute).
  - The max run gain must be >= 5% to qualify.

Top N gappers per day are selected by max run gain.

Pillars recorded at first available minute at/after 9:29 ET:
  - day_gain_pct_929plus (vs previous day close)
  - rel_vol_30d (from 1m table at that minute)
  - float_lt_20m (from stock_fundamentals)
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
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


def load_float_map(conn, schema: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol, float_shares FROM {schema}.stock_fundamentals")
        return {row[0]: row[1] for row in cur.fetchall()}


def load_prev_close_map(conn, schema: str, start: date, end: date) -> dict[tuple[date, str], float]:
    # Include one day before start for LAG
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


@dataclass
class GapperRow:
    trade_date: date
    symbol: str
    max_run_gain_pct: float
    run_start_time_et: datetime
    run_end_time_et: datetime
    run_minutes: int
    price_929plus: float | None
    day_gain_pct_929plus: float | None
    rel_vol_30d_929plus: float | None
    float_shares: int | None
    float_lt_20m: bool | None


def compute_max_green_run(group: pd.DataFrame) -> tuple[float, datetime, datetime, int] | None:
    # group must be sorted by time
    times = group["time"].values
    opens = group["open"].astype(float).values
    closes = group["close"].astype(float).values

    max_gain = -1.0
    max_start = None
    max_end = None
    max_len = 0

    run_start_idx = None
    for i in range(len(group)):
        is_green = closes[i] > opens[i]
        if not is_green:
            run_start_idx = None
            continue

        if run_start_idx is None:
            run_start_idx = i
        else:
            # ensure consecutive minute
            dt_minutes = int((times[i] - times[i - 1]) / pd.Timedelta(minutes=1))
            if dt_minutes != 1:
                run_start_idx = i

        run_end_idx = i
        start_open = opens[run_start_idx]
        end_close = closes[run_end_idx]
        if start_open > 0:
            gain = (end_close / start_open - 1.0) * 100.0
            run_len = run_end_idx - run_start_idx + 1
            if gain > max_gain:
                max_gain = gain
                max_start = group.iloc[run_start_idx]["time"]
                max_end = group.iloc[run_end_idx]["time"]
                max_len = run_len

    if max_gain < 0:
        return None
    return max_gain, max_start.to_pydatetime(), max_end.to_pydatetime(), max_len


def fetch_minute_data_for_day(conn, schema: str, d: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(d, 0, 0))
    end_utc = et_to_utc(et_at(d + timedelta(days=1), 0, 0))
    sql = f"""
    SELECT time, symbol, open, close, rel_vol_30d
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ORDER BY symbol, time;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["time", "symbol", "open", "close", "rel_vol_30d"])
    df = pd.DataFrame(rows, columns=["time", "symbol", "open", "close", "rel_vol_30d"])
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Find top N gappers per day")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--top-n", type=int, default=5, help="Top N gappers per day")
    parser.add_argument("--min-gain", type=float, default=5.0, help="Min run gain percent")
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default database/audit_reports/top_gappers_<start>_<end>.csv)",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    output_path = args.output or os.path.join(
        "database",
        "audit_reports",
        f"top_gappers_{args.start}_{args.end}.csv",
    )

    conn = psycopg2.connect(DB_CONN)
    try:
        float_map = load_float_map(conn, args.schema)
        prev_close_map = load_prev_close_map(conn, args.schema, start, end)

        rows: list[GapperRow] = []
        for d in daterange(start, end):
            df = fetch_minute_data_for_day(conn, args.schema, d)
            if df.empty:
                continue

            df["time"] = pd.to_datetime(df["time"], utc=True)

            results = []
            for symbol, group in df.groupby("symbol", sort=False):
                group = group.sort_values("time")
                res = compute_max_green_run(group)
                if res is None:
                    continue
                max_gain, run_start, run_end, run_len = res
                if max_gain < args.min_gain:
                    continue
                results.append((symbol, max_gain, run_start, run_end, run_len))

            if not results:
                continue

            # pick top N by max_gain
            results.sort(key=lambda x: x[1], reverse=True)
            top = results[: args.top_n]

            # compute 9:29+ price and rel vol for top symbols
            t929 = et_to_utc(et_at(d, 9, 29))
            df_929 = df[df["time"] >= t929]
            for symbol, max_gain, run_start, run_end, run_len in top:
                sym_rows = df_929[df_929["symbol"] == symbol]
                price_929 = None
                rel_vol_929 = None
                if not sym_rows.empty:
                    first_row = sym_rows.iloc[0]
                    price_929 = float(first_row["close"]) if first_row["close"] is not None else None
                    rel_vol_929 = (
                        float(first_row["rel_vol_30d"])
                        if first_row["rel_vol_30d"] is not None
                        else None
                    )

                prev_close = prev_close_map.get((d, symbol))
                day_gain_pct_929plus = None
                if price_929 and prev_close:
                    day_gain_pct_929plus = (price_929 / prev_close - 1.0) * 100.0

                float_shares = float_map.get(symbol)
                float_lt_20m = (
                    (float_shares is not None and float_shares < 20_000_000)
                    if float_shares is not None
                    else None
                )

                rows.append(
                    GapperRow(
                        trade_date=d,
                        symbol=symbol,
                        max_run_gain_pct=max_gain,
                        run_start_time_et=run_start.astimezone(ET_TZ),
                        run_end_time_et=run_end.astimezone(ET_TZ),
                        run_minutes=run_len,
                        price_929plus=price_929,
                        day_gain_pct_929plus=day_gain_pct_929plus,
                        rel_vol_30d_929plus=rel_vol_929,
                        float_shares=int(float_shares) if float_shares is not None else None,
                        float_lt_20m=float_lt_20m,
                    )
                )
    finally:
        conn.close()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out_df = pd.DataFrame(
        [
            {
                "trade_date": r.trade_date.isoformat(),
                "symbol": r.symbol,
                "max_run_gain_pct": r.max_run_gain_pct,
                "run_start_time_et": r.run_start_time_et.isoformat(),
                "run_end_time_et": r.run_end_time_et.isoformat(),
                "run_minutes": r.run_minutes,
                "price_929plus": r.price_929plus,
                "day_gain_pct_929plus": r.day_gain_pct_929plus,
                "rel_vol_30d_929plus": r.rel_vol_30d_929plus,
                "float_shares": r.float_shares,
                "float_lt_20m": r.float_lt_20m,
            }
            for r in rows
        ]
    )
    out_df.to_csv(output_path, index=False)
    print(f"Wrote {len(out_df)} rows to {output_path}")


if __name__ == "__main__":
    main()
