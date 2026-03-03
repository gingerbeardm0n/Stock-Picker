#!/usr/bin/env python3
"""
Build rel_vol cumulative cache for fast rel_vol_30d backfill.

Cache table: <schema>.rel_vol_cum_cache
  trade_date, symbol, minute_of_day, cum_total

cum_total = premarket_volume(4am-8am ET, from 1h bars)
           + cumulative_minute_volume(8am-12/1pm ET, from 1m bars)
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

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


def et_at_hour(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=ET_TZ)


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def build_for_date(
    conn,
    target_date: date,
    schema: str,
    minute_start: int,
    minute_end: int,
    hour_start: int,
    hour_end: int,
    purge: bool,
) -> None:
    minute_start_utc = et_to_utc(et_at_hour(target_date, minute_start))
    minute_end_utc = et_to_utc(et_at_hour(target_date, minute_end))
    hour_start_utc = et_to_utc(et_at_hour(target_date, hour_start))
    hour_end_utc = et_to_utc(et_at_hour(target_date, hour_end))

    sql = f"""
    SET LOCAL work_mem = '256MB';

    CREATE TABLE IF NOT EXISTS {schema}.rel_vol_cum_cache (
        trade_date date NOT NULL,
        symbol varchar(10) NOT NULL,
        minute_of_day int NOT NULL,
        cum_total double precision NOT NULL,
        PRIMARY KEY (trade_date, symbol, minute_of_day)
    );

    CREATE INDEX IF NOT EXISTS rel_vol_cum_cache_symbol_minute_date
        ON {schema}.rel_vol_cum_cache (symbol, minute_of_day, trade_date);

    {"DELETE FROM " + schema + ".rel_vol_cum_cache WHERE trade_date = %s;" if purge else ""}

    DROP TABLE IF EXISTS tmp_premarket;
    DROP TABLE IF EXISTS tmp_minutes;

    CREATE TEMP TABLE tmp_premarket ON COMMIT DROP AS
    SELECT
        symbol,
        SUM(volume)::double precision AS premarket_vol
    FROM {schema}.stock_candles_1h
    WHERE time >= %s::timestamptz
      AND time <  %s::timestamptz
    GROUP BY symbol;

    CREATE TEMP TABLE tmp_minutes ON COMMIT DROP AS
    SELECT
        time,
        symbol,
        (EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York')::int * 60
         + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York')::int) AS minute_of_day,
        SUM(volume) OVER (
            PARTITION BY symbol
            ORDER BY time
        )::double precision AS cum_minute_vol
    FROM {schema}.stock_candles_1m
    WHERE time >= %s::timestamptz
      AND time <  %s::timestamptz;

    INSERT INTO {schema}.rel_vol_cum_cache (trade_date, symbol, minute_of_day, cum_total)
    SELECT
        %s::date AS trade_date,
        m.symbol,
        m.minute_of_day,
        (COALESCE(p.premarket_vol, 0) + m.cum_minute_vol) AS cum_total
    FROM tmp_minutes m
    LEFT JOIN tmp_premarket p
      ON p.symbol = m.symbol
    ON CONFLICT (trade_date, symbol, minute_of_day)
    DO UPDATE SET cum_total = EXCLUDED.cum_total;
    """

    with conn.cursor() as cur:
        params = []
        if purge:
            params.append(target_date)
        params.extend(
            [
                hour_start_utc,
                hour_end_utc,
                minute_start_utc,
                minute_end_utc,
                target_date,
            ]
        )
        cur.execute(sql, params)
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rel_vol cumulative cache")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--start", help="Start date YYYY-MM-DD (inclusive)")
    parser.add_argument("--end", help="End date YYYY-MM-DD (inclusive)")
    parser.add_argument("--minute-start", type=int, default=8, help="Minute window ET start hour")
    parser.add_argument("--minute-end", type=int, default=13, help="Minute window ET end hour (exclusive)")
    parser.add_argument("--hour-start", type=int, default=4, help="Premarket hour window ET start")
    parser.add_argument("--hour-end", type=int, default=8, help="Premarket hour window ET end (exclusive)")
    parser.add_argument("--purge", action="store_true", help="Purge cache rows for date(s) before insert")
    args = parser.parse_args()

    if args.date:
        start = end = parse_date(args.date)
    elif args.start and args.end:
        start = parse_date(args.start)
        end = parse_date(args.end)
    else:
        raise SystemExit("Provide --date or both --start and --end")

    conn = psycopg2.connect(DB_CONN)
    try:
        for d in daterange(start, end):
            build_for_date(
                conn=conn,
                target_date=d,
                schema=args.schema,
                minute_start=args.minute_start,
                minute_end=args.minute_end,
                hour_start=args.hour_start,
                hour_end=args.hour_end,
                purge=args.purge,
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
