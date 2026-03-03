#!/usr/bin/env python3
"""
Scan minute candles for "gap-up" events and export pillar values to CSV.

Gap-up definition (per minute candle):
  A) 3%+ over at least 3 minutes with consistent rise:
     close_t > close_{t-1} > close_{t-2} AND close_t / close_{t-2} - 1 >= 0.03
  OR
  B) 10%+ in a single minute:
     close_t / open_t - 1 >= 0.10

Scan window: 9:28–11:00 ET (inclusive start, exclusive end)
Pillars recorded:
  - Up 10%+ on the Day (uses first minute at/after 9:29 ET vs yesterday close)
  - Relative Volume (rel_vol_30d at event minute)
  - Float < 20M (from stock_fundamentals.float_shares)
  - News Catalyst (via backend.news_fetcher)
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from dotenv import load_dotenv

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from backend.news_fetcher import NewsFetcher

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


def et_to_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC_TZ)


def et_at(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET_TZ)


@dataclass
class EventRow:
    symbol: str
    event_time_utc: datetime
    event_time_et: datetime
    event_type: str
    open_price: float
    close_price: float
    pct_move_1m: float | None
    pct_move_3m: float | None
    rel_vol_30d: float | None
    prev_close: float | None
    price_929: float | None
    day_gain_pct_929plus: float | None
    day_gain_pct_event: float | None
    float_shares: int | None
    float_lt_20m: bool | None
    pillar_day_gain_10pct: bool | None
    pillar_rel_vol_5x: bool | None
    pillar_score: int | None
    news_has_catalyst: bool | None
    news_article_count: int | None
    news_specific_count: int | None


def fetch_gap_events_for_day(conn, schema: str, d: date) -> list[EventRow]:
    start_utc = et_to_utc(et_at(d, 9, 28))
    end_utc = et_to_utc(et_at(d, 11, 0))
    price_929_start = et_to_utc(et_at(d, 9, 29))
    price_929_end = et_to_utc(et_at(d, 11, 0))

    sql = f"""
    WITH daily_prev AS (
        SELECT
            symbol,
            (time AT TIME ZONE 'America/New_York')::date AS trade_date,
            close,
            LAG(close) OVER (
                PARTITION BY symbol
                ORDER BY (time AT TIME ZONE 'America/New_York')::date
            ) AS prev_close
        FROM {schema}.stock_candles_1d
    ),
    price_929 AS (
        SELECT DISTINCT ON (symbol)
            symbol,
            close AS price_929
        FROM {schema}.stock_candles_1m
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
        ORDER BY symbol, time ASC
    ),
    minute_data AS (
        SELECT
            time,
            symbol,
            open,
            close,
            rel_vol_30d,
            LAG(close, 1) OVER (PARTITION BY symbol ORDER BY time) AS prev_close_1m,
            LAG(close, 2) OVER (PARTITION BY symbol ORDER BY time) AS prev_close_2m,
            LAG(open, 1) OVER (PARTITION BY symbol ORDER BY time) AS prev_open_1m,
            LAG(open, 2) OVER (PARTITION BY symbol ORDER BY time) AS prev_open_2m
        FROM {schema}.stock_candles_1m
        WHERE time >= %s::timestamptz AND time < %s::timestamptz
    ),
    flags AS (
        SELECT
            m.*,
            CASE
                WHEN m.prev_close_2m IS NOT NULL
                 AND (
                       (m.close > m.prev_close_1m AND m.prev_close_1m > m.prev_close_2m)
                    OR (m.open IS NOT NULL AND m.prev_open_1m IS NOT NULL AND m.prev_open_2m IS NOT NULL
                        AND m.close > m.open
                        AND m.prev_close_1m > m.prev_open_1m
                        AND m.prev_close_2m > m.prev_open_2m)
                 )
                 AND (m.close / m.prev_close_2m - 1.0) >= 0.03
                THEN TRUE ELSE FALSE
            END AS gap_3m,
            CASE
                WHEN m.open > 0
                 AND (m.close / m.open - 1.0) >= 0.10
                THEN TRUE ELSE FALSE
            END AS gap_1m
        FROM minute_data m
    )
    SELECT
        f.time,
        f.symbol,
        f.open,
        f.close,
        f.rel_vol_30d,
        f.prev_close_1m,
        f.prev_close_2m,
        f.gap_3m,
        f.gap_1m,
        d.prev_close,
        p.price_929
    FROM flags f
    LEFT JOIN daily_prev d
      ON d.symbol = f.symbol
     AND d.trade_date = %s::date
    LEFT JOIN price_929 p
      ON p.symbol = f.symbol
    WHERE f.gap_3m = TRUE OR f.gap_1m = TRUE
    ORDER BY f.time, f.symbol;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                price_929_start,
                price_929_end,
                start_utc,
                end_utc,
                d,
            ),
        )
        rows = cur.fetchall()

    results: list[EventRow] = []
    for (
        time_utc,
        symbol,
        open_price,
        close_price,
        rel_vol_30d,
        prev_close_1m,
        prev_close_2m,
        gap_3m,
        gap_1m,
        prev_close_day,
        price_929,
    ) in rows:
        time_et = time_utc.astimezone(ET_TZ)
        open_f = float(open_price) if open_price is not None else None
        close_f = float(close_price) if close_price is not None else None
        prev_close_2m_f = float(prev_close_2m) if prev_close_2m is not None else None
        prev_close_day_f = (
            float(prev_close_day) if prev_close_day is not None else None
        )
        price_929_f = float(price_929) if price_929 is not None else None

        pct_move_1m = (
            (close_f / open_f - 1.0) * 100.0 if open_f and close_f else None
        )
        pct_move_3m = (
            (close_f / prev_close_2m_f - 1.0) * 100.0
            if prev_close_2m_f and close_f
            else None
        )
        event_type = "gap_3m_3pct" if gap_3m else "gap_1m_10pct"
        day_gain_pct_929plus = (
            (price_929_f / prev_close_day_f - 1.0) * 100.0
            if price_929_f and prev_close_day_f
            else None
        )
        day_gain_pct_event = (
            (close_f / prev_close_day_f - 1.0) * 100.0
            if close_f and prev_close_day_f
            else None
        )

        results.append(
            EventRow(
                symbol=symbol,
                event_time_utc=time_utc,
                event_time_et=time_et,
                event_type=event_type,
                open_price=open_f if open_f is not None else 0.0,
                close_price=close_f if close_f is not None else 0.0,
                pct_move_1m=pct_move_1m,
                pct_move_3m=pct_move_3m,
                rel_vol_30d=float(rel_vol_30d) if rel_vol_30d is not None else None,
                prev_close=prev_close_day_f,
                price_929=price_929_f,
                day_gain_pct_929plus=day_gain_pct_929plus,
                day_gain_pct_event=day_gain_pct_event,
                float_shares=None,
                float_lt_20m=None,
                pillar_day_gain_10pct=None,
                pillar_rel_vol_5x=None,
                pillar_score=None,
                news_has_catalyst=None,
                news_article_count=None,
                news_specific_count=None,
            )
        )

    return results


def load_float_map(conn, schema: str) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute(f"SELECT symbol, float_shares FROM {schema}.stock_fundamentals")
        return {row[0]: row[1] for row in cur.fetchall()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Find gap-up events and export CSV")
    parser.add_argument("--schema", default="public", help="Target schema")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default database/audit_reports/gap_up_events_<start>_<end>.csv)",
    )
    parser.add_argument("--news-hours-back", type=int, default=48, help="News lookback window")
    parser.add_argument(
        "--disable-news",
        action="store_true",
        help="Skip news API calls (sets news fields to NULL)",
    )
    args = parser.parse_args()

    start = parse_date(args.start)
    end = parse_date(args.end)
    output_path = args.output or os.path.join(
        "database",
        "audit_reports",
        f"gap_up_events_{args.start}_{args.end}.csv",
    )

    conn = psycopg2.connect(DB_CONN)
    try:
        float_map = load_float_map(conn, args.schema)
        news = None if args.disable_news else NewsFetcher()
        if not args.disable_news:
            logging.getLogger("backend.news_fetcher").setLevel(logging.CRITICAL)
        news_cache: dict[tuple[str, date], tuple[bool, list[dict]]] = {}
        news_failed = False

        rows: list[EventRow] = []
        for d in daterange(start, end):
            day_events = fetch_gap_events_for_day(conn, args.schema, d)
            if not day_events:
                continue

            for ev in day_events:
                float_shares = float_map.get(ev.symbol)
                ev.float_shares = int(float_shares) if float_shares is not None else None
                ev.float_lt_20m = (
                    (float_shares is not None and float_shares < 20_000_000)
                    if float_shares is not None
                    else None
                )
                ev.pillar_day_gain_10pct = (
                    ev.day_gain_pct_929plus is not None
                    and ev.day_gain_pct_929plus >= 10.0
                )
                ev.pillar_rel_vol_5x = (
                    ev.rel_vol_30d is not None and ev.rel_vol_30d >= 5.0
                )
                pillar_float = bool(ev.float_lt_20m) if ev.float_lt_20m is not None else False
                ev.pillar_score = (
                    int(bool(ev.pillar_day_gain_10pct))
                    + int(bool(ev.pillar_rel_vol_5x))
                    + int(pillar_float)
                )

                if args.disable_news:
                    ev.news_has_catalyst = None
                    ev.news_article_count = None
                    ev.news_specific_count = None
                else:
                    if news_failed:
                        ev.news_has_catalyst = None
                        ev.news_article_count = None
                        ev.news_specific_count = None
                    else:
                        cache_key = (ev.symbol, d)
                        try:
                            if cache_key not in news_cache:
                                has_cat, articles = news.has_catalyst(
                                    ev.symbol, as_of_date=d, hours_back=args.news_hours_back
                                )
                                news_cache[cache_key] = (has_cat, articles)
                            else:
                                has_cat, articles = news_cache[cache_key]

                            ev.news_has_catalyst = has_cat
                            ev.news_article_count = len(articles)
                            ev.news_specific_count = len(
                                [a for a in articles if a.get("is_specific")]
                            )
                        except Exception as exc:
                            news_failed = True
                            ev.news_has_catalyst = None
                            ev.news_article_count = None
                            ev.news_specific_count = None
                            print(f"News fetch failed, disabling news for rest of run: {exc}")

            rows.extend(day_events)
    finally:
        conn.close()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "symbol",
                "event_time_et",
                "event_time_utc",
                "event_type",
                "open",
                "close",
                "pct_move_1m",
                "pct_move_3m",
                "rel_vol_30d",
                "prev_close",
                "price_929",
                "day_gain_pct_929plus",
                "day_gain_pct_event",
                "float_shares",
                "float_lt_20m",
                "pillar_day_gain_10pct",
                "pillar_rel_vol_5x",
                "pillar_score",
                "news_has_catalyst",
                "news_article_count",
                "news_specific_count",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.symbol,
                    r.event_time_et.isoformat(),
                    r.event_time_utc.isoformat(),
                    r.event_type,
                    r.open_price,
                    r.close_price,
                    r.pct_move_1m,
                    r.pct_move_3m,
                    r.rel_vol_30d,
                    r.prev_close,
                    r.price_929,
                    r.day_gain_pct_929plus,
                    r.day_gain_pct_event,
                    r.float_shares,
                    r.float_lt_20m,
                    r.pillar_day_gain_10pct,
                    r.pillar_rel_vol_5x,
                    r.pillar_score,
                    r.news_has_catalyst,
                    r.news_article_count,
                    r.news_specific_count,
                ]
            )

    print(f"Wrote {len(rows)} events to {output_path}")


if __name__ == "__main__":
    main()
