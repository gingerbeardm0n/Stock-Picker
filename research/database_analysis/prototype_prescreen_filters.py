#!/usr/bin/env python3
"""
Prototype prescreen filters based on premarket volatility + last-5-minute range/volume.

Screening time: first available minute at or after 9:29 ET per symbol/day.
Features computed from data BEFORE that minute.
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


def load_float_map(conn, schema: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol, float_shares FROM {schema}.stock_fundamentals")
        return {row[0]: row[1] for row in cur.fetchall()}


def fetch_minutes_for_day(conn, schema: str, d: date) -> pd.DataFrame:
    start_utc = et_to_utc(et_at(d, 0, 0))
    end_utc = et_to_utc(et_at(d + timedelta(days=1), 0, 0))
    sql = f"""
    SELECT time, symbol, open, high, low, close, volume, trade_count, rel_vol_30d
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ORDER BY symbol, time;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_utc, end_utc))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(
            columns=["time", "symbol", "open", "high", "low", "close", "volume", "trade_count", "rel_vol_30d"]
        )
    df = pd.DataFrame(rows, columns=["time", "symbol", "open", "high", "low", "close", "volume", "trade_count", "rel_vol_30d"])
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for col in ["open", "high", "low", "close", "volume", "trade_count", "rel_vol_30d"]:
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


def compute_premarket_agg(prem: pd.DataFrame) -> dict[str, dict]:
    out = {}
    if prem.empty:
        return out
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
            (pre_high - pre_low) / pre_open * 100.0 if pre_open and pre_open > 0 else None
        )
        out[symbol] = {
            "pre_vol_4_8": pre_vol,
            "pre_trend_pct": pre_trend_pct,
            "pre_range_pct_4_8": pre_range_pct,
        }
    return out


@dataclass
class ScreenRow:
    trade_date: date
    symbol: str
    price_929plus: float | None
    day_gain_pct_929plus: float | None
    rel_vol_30d_929plus: float | None
    float_lt_20m: bool | None
    pre_range_pct_4_8: float | None
    last5_range_pct: float | None
    last5_volume_sum: float | None
    pre_trade_count: float | None


def build_screen_rows(
    conn,
    schema: str,
    d: date,
    prev_close_map: dict[tuple[date, str], float],
    float_map: dict[str, int],
) -> list[ScreenRow]:
    mins = fetch_minutes_for_day(conn, schema, d)
    if mins.empty:
        return []
    prem = fetch_premarket_hours(conn, schema, d)
    pre_agg = compute_premarket_agg(prem)

    t929 = et_to_utc(et_at(d, 9, 29))
    rows: list[ScreenRow] = []

    for symbol, g in mins.groupby("symbol", sort=False):
        g = g.sort_values("time").reset_index(drop=True)
        g_after = g[g["time"] >= t929]
        if g_after.empty:
            continue
        screen = g_after.iloc[0]
        screen_idx = int(screen.name)

        # last 5 minutes before screen minute
        pre_idx = screen_idx - 1
        last5 = None
        if pre_idx >= 0:
            last5_start = max(0, screen_idx - 5)
            last5 = g.loc[last5_start:pre_idx]

        last5_range_pct = None
        last5_volume_sum = None
        if last5 is not None and not last5.empty:
            o0 = last5["open"].iloc[0]
            if o0 and o0 > 0:
                last5_range_pct = (last5["high"].max() - last5["low"].min()) / o0 * 100.0
            last5_volume_sum = last5["volume"].sum()

        prev_close = prev_close_map.get((d, symbol))
        price_929 = float(screen["close"]) if screen["close"] is not None else None
        day_gain = (price_929 / prev_close - 1.0) * 100.0 if price_929 and prev_close else None

        float_shares = float_map.get(symbol)
        float_lt = (
            (float_shares is not None and float_shares < 20_000_000)
            if float_shares is not None
            else None
        )

        rows.append(
            ScreenRow(
                trade_date=d,
                symbol=symbol,
                price_929plus=price_929,
                day_gain_pct_929plus=day_gain,
                rel_vol_30d_929plus=float(screen["rel_vol_30d"]) if screen["rel_vol_30d"] is not None else None,
                float_lt_20m=float_lt,
                pre_range_pct_4_8=pre_agg.get(symbol, {}).get("pre_range_pct_4_8"),
                last5_range_pct=last5_range_pct,
                last5_volume_sum=last5_volume_sum,
                pre_trade_count=float(screen["trade_count"]) if screen["trade_count"] is not None else None,
            )
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Prototype prescreen filters")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--output", default=None, help="Output CSV path")
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    output_path = args.output or os.path.join(
        "database",
        "audit_reports",
        f"prototype_prescreen_filters_{args.start}_{args.end}.csv",
    )

    conn = psycopg2.connect(DB_CONN)
    try:
        prev_close_map = load_prev_close_map(conn, args.schema, start, end)
        float_map = load_float_map(conn, args.schema)
        rows: list[ScreenRow] = []
        d = start
        while d <= end:
            rows.extend(build_screen_rows(conn, args.schema, d, prev_close_map, float_map))
            d += timedelta(days=1)
    finally:
        conn.close()

    df = pd.DataFrame([r.__dict__ for r in rows])
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()
