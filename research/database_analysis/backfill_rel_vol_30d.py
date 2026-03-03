#!/usr/bin/env python3
"""
Backfill rel_vol_30d for stock_candles_1m using a precomputed cache.

Rel vol definition:
  cumulative_volume_today(4am -> current minute) /
  avg cumulative_volume(4am -> same minute) over last N days

Premarket volume (4am-8am) is sourced from 1h bars.
Minute volume (8am-12pm/1pm) is sourced from 1m bars.
"""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONN = os.getenv(
    "TIMESCALE_CONNECTION_STRING",
    "postgresql://postgres:changeme123@localhost:5432/stockdata",
)


ET_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def et_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=ET_TZ)


def et_at_hour(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=ET_TZ)


def run_for_date(
    conn,
    target_date: date,
    lookback_days: int,
    schema: str,
    minute_start: int,
    minute_end: int,
    hour_start: int,
    hour_end: int,
) -> None:
    hist_start_utc = et_to_utc(et_day_start(target_date - timedelta(days=lookback_days)))
    hist_end_utc = et_to_utc(et_day_start(target_date))
    today_minute_start_utc = et_to_utc(et_at_hour(target_date, minute_start))
    today_minute_end_utc = et_to_utc(et_at_hour(target_date, minute_end))
    today_hour_start_utc = et_to_utc(et_at_hour(target_date, hour_start))
    today_hour_end_utc = et_to_utc(et_at_hour(target_date, hour_end))

    sql = f"""
    SET LOCAL work_mem = '256MB';
    CREATE TEMP TABLE tmp_params (
        target_date date,
        hist_start_utc timestamptz,
        hist_end_utc timestamptz,
        today_minute_start_utc timestamptz,
        today_minute_end_utc timestamptz,
        today_hour_start_utc timestamptz,
        today_hour_end_utc timestamptz,
        minute_start int,
        minute_end int,
        hour_start int,
        hour_end int
    );

    INSERT INTO tmp_params (
        target_date,
        hist_start_utc,
        hist_end_utc,
        today_minute_start_utc,
        today_minute_end_utc,
        today_hour_start_utc,
        today_hour_end_utc,
        minute_start,
        minute_end,
        hour_start,
        hour_end
    ) VALUES (
        %s::date,
        %s::timestamptz,
        %s::timestamptz,
        %s::timestamptz,
        %s::timestamptz,
        %s::timestamptz,
        %s::timestamptz,
        %s::int,
        %s::int,
        %s::int,
        %s::int
    );

    CREATE TABLE IF NOT EXISTS {schema}.rel_vol_cum_cache (
        trade_date date NOT NULL,
        symbol varchar(10) NOT NULL,
        minute_of_day int NOT NULL,
        cum_total double precision NOT NULL,
        PRIMARY KEY (trade_date, symbol, minute_of_day)
    );

    CREATE INDEX IF NOT EXISTS rel_vol_cum_cache_symbol_minute_date
        ON {schema}.rel_vol_cum_cache (symbol, minute_of_day, trade_date);

    CREATE TEMP TABLE tmp_avg_cum AS
    SELECT
        symbol,
        minute_of_day,
        AVG(cum_total)::double precision AS avg_cum_total
    FROM {schema}.rel_vol_cum_cache
    WHERE trade_date < (SELECT target_date FROM tmp_params)
      AND trade_date >= (SELECT target_date FROM tmp_params) - INTERVAL '1 day' * %s
    GROUP BY symbol, minute_of_day;

    CREATE INDEX ON tmp_avg_cum (symbol, minute_of_day);

    CREATE TEMP TABLE tmp_today_rows AS
    SELECT
        m.time,
        m.symbol,
        (EXTRACT(HOUR FROM m.time AT TIME ZONE 'America/New_York')::int * 60
         + EXTRACT(MINUTE FROM m.time AT TIME ZONE 'America/New_York')::int) AS minute_of_day
    FROM {schema}.stock_candles_1m m
    WHERE m.time >= (SELECT today_minute_start_utc FROM tmp_params)
      AND m.time <  (SELECT today_minute_end_utc FROM tmp_params);

    UPDATE {schema}.stock_candles_1m m
       SET rel_vol_30d = CASE
            WHEN a.avg_cum_total > 0 THEN (c.cum_total / a.avg_cum_total)
            ELSE NULL
        END
      FROM tmp_today_rows t
      JOIN {schema}.rel_vol_cum_cache c
        ON c.trade_date = (SELECT target_date FROM tmp_params)
       AND c.symbol = t.symbol
       AND c.minute_of_day = t.minute_of_day
      LEFT JOIN tmp_avg_cum a
        ON a.symbol = t.symbol
       AND a.minute_of_day = t.minute_of_day
     WHERE m.time = t.time
       AND m.symbol = t.symbol;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                target_date,
                hist_start_utc,
                hist_end_utc,
                today_minute_start_utc,
                today_minute_end_utc,
                today_hour_start_utc,
                today_hour_end_utc,
                minute_start,
                minute_end,
                hour_start,
                hour_end,
                lookback_days,
            ),
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill rel_vol_30d for stock_candles_1m")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=30, help="Lookback window in days")
    parser.add_argument("--minute-start", type=int, default=8, help="Minute window ET start hour")
    parser.add_argument("--minute-end", type=int, default=13, help="Minute window ET end hour (exclusive)")
    parser.add_argument("--hour-start", type=int, default=4, help="Premarket hour window ET start")
    parser.add_argument("--hour-end", type=int, default=8, help="Premarket hour window ET end (exclusive)")
    args = parser.parse_args()

    target = parse_date(args.date)
    conn = psycopg2.connect(DB_CONN)
    try:
        run_for_date(
            conn=conn,
            target_date=target,
            lookback_days=args.lookback_days,
            schema=args.schema,
            minute_start=args.minute_start,
            minute_end=args.minute_end,
            hour_start=args.hour_start,
            hour_end=args.hour_end,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
