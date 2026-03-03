#!/usr/bin/env python3
"""
Bootstrap one trading day of data with strict completeness checks.

Workflow:
1) Build a symbol universe from current tradable stocks in a price range.
2) Fetch previous-trading-day daily bars for that universe.
3) Fetch target-day hourly bars in a configurable ET window (default 4:00-8:00, end-exclusive).
4) Fetch target-day minute bars in a configurable ET window (default 8:00-12:00, end-exclusive).
5) Validate expected bars per symbol and retry only missing symbols.

Usage:
  python database/bootstrap_single_day_data.py --date 2026-02-20
  python database/bootstrap_single_day_data.py --date 2026-02-20 --hour-end 9  # expect 5 hourly bars
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dtime, timedelta
from typing import Dict, List

import pytz
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import Config
from services.fetch_stocks_in_price_range import (  # noqa: E402
    get_all_tradable_stocks,
    get_stocks_in_price_range,
)
from utils.query_helpers import StockDataDB  # noqa: E402
from utils.trading_calendar import get_trading_days as get_nyse_trading_days  # noqa: E402

load_dotenv()

ET = pytz.timezone("America/New_York")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    stage: str
    expected_bars_per_symbol: int
    target_symbol_count: int
    complete_symbol_count: int
    missing_symbol_count: int
    fetched_bar_rows: int
    retries_used: int
    missing_symbols_sample: List[str]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_schema(value: str) -> str:
    # Keep schema names simple and safe because table references are string-formatted.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid schema name: {value!r}")
    return value


def to_et_datetime(trade_date: date, hour: int) -> datetime:
    return ET.localize(datetime.combine(trade_date, dtime(hour=hour, minute=0)))


def get_previous_trading_day(target_day: date) -> date:
    lookback_start = target_day - timedelta(days=14)
    days = [d for d in get_nyse_trading_days(lookback_start, target_day - timedelta(days=1))]
    if not days:
        raise ValueError(f"No prior trading day found before {target_day}")
    return days[-1]


def store_candles(db: StockDataDB, bars_response, table_name: str) -> int:
    inserted = 0
    cursor = db.conn.cursor()
    for symbol, bars in bars_response.data.items():
        for bar in bars:
            cursor.execute(
                f"""
                INSERT INTO {table_name}
                (time, symbol, open, high, low, close, volume, trade_count, vwap)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (time, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    trade_count = EXCLUDED.trade_count,
                    vwap = EXCLUDED.vwap
                """,
                (
                    bar.timestamp,
                    symbol,
                    float(bar.open),
                    float(bar.high),
                    float(bar.low),
                    float(bar.close),
                    int(bar.volume),
                    int(bar.trade_count) if getattr(bar, "trade_count", None) is not None else None,
                    float(bar.vwap) if bar.vwap is not None else None,
                ),
            )
            inserted += 1
    db.conn.commit()
    cursor.close()
    return inserted


def fetch_bars_for_symbols(
    client: StockHistoricalDataClient,
    db: StockDataDB,
    symbols: List[str],
    timeframe: TimeFrame,
    start_dt: datetime,
    end_dt: datetime,
    feed: str,
    table_name: str,
    chunk_size: int,
    sleep_seconds: float,
) -> int:
    if not symbols:
        return 0

    total_inserted = 0
    total_chunks = (len(symbols) - 1) // chunk_size + 1
    for idx in range(0, len(symbols), chunk_size):
        chunk = symbols[idx : idx + chunk_size]
        chunk_num = idx // chunk_size + 1
        logger.info(
            "  Fetching %s chunk %s/%s (%s symbols)",
            table_name,
            chunk_num,
            total_chunks,
            len(chunk),
        )
        request = StockBarsRequest(
            symbol_or_symbols=chunk,
            timeframe=timeframe,
            start=start_dt,
            end=end_dt,
            feed=feed,
        )
        bars = client.get_stock_bars(request)
        total_inserted += store_candles(db, bars, table_name)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return total_inserted


def get_symbol_counts(
    db: StockDataDB,
    table_name: str,
    symbols: List[str],
    trade_date: date,
    start_hour: int | None = None,
    end_hour: int | None = None,
) -> Dict[str, int]:
    if not symbols:
        return {}

    cursor = db.conn.cursor()
    if start_hour is None or end_hour is None:
        cursor.execute(
            f"""
            SELECT symbol, COUNT(*)::int
            FROM {table_name}
            WHERE symbol = ANY(%s)
              AND (time AT TIME ZONE 'America/New_York')::date = %s::date
            GROUP BY symbol
            """,
            (symbols, trade_date),
        )
    else:
        cursor.execute(
            f"""
            SELECT symbol, COUNT(*)::int
            FROM {table_name}
            WHERE symbol = ANY(%s)
              AND (time AT TIME ZONE 'America/New_York')::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            GROUP BY symbol
            """,
            (symbols, trade_date, start_hour, end_hour),
        )
    rows = cursor.fetchall()
    cursor.close()
    return {symbol: count for symbol, count in rows}


def run_stage_with_retries(
    *,
    stage_name: str,
    client: StockHistoricalDataClient,
    db: StockDataDB,
    symbols: List[str],
    table_name: str,
    timeframe: TimeFrame,
    fetch_start: datetime,
    fetch_end: datetime,
    validate_date: date,
    expected_bars: int,
    validate_start_hour: int | None,
    validate_end_hour: int | None,
    feed: str,
    chunk_size: int,
    max_retries: int,
    retry_sleep_seconds: float,
) -> StageResult:
    retries_used = 0
    total_inserted = 0
    pending = list(symbols)
    counts: Dict[str, int] = {}

    for attempt in range(max_retries + 1):
        logger.info(
            "%s attempt %s/%s for %s symbols",
            stage_name,
            attempt + 1,
            max_retries + 1,
            len(pending),
        )
        if pending:
            total_inserted += fetch_bars_for_symbols(
                client=client,
                db=db,
                symbols=pending,
                timeframe=timeframe,
                start_dt=fetch_start,
                end_dt=fetch_end,
                feed=feed,
                table_name=table_name,
                chunk_size=chunk_size,
                sleep_seconds=retry_sleep_seconds,
            )

        counts = get_symbol_counts(
            db=db,
            table_name=table_name,
            symbols=symbols,
            trade_date=validate_date,
            start_hour=validate_start_hour,
            end_hour=validate_end_hour,
        )
        pending = [s for s in symbols if counts.get(s, 0) < expected_bars]
        if not pending:
            break
        retries_used = attempt + 1
        if attempt < max_retries:
            logger.warning("%s still missing for %s symbols; retrying...", stage_name, len(pending))

    complete_count = sum(1 for s in symbols if counts.get(s, 0) == expected_bars)
    return StageResult(
        stage=stage_name,
        expected_bars_per_symbol=expected_bars,
        target_symbol_count=len(symbols),
        complete_symbol_count=complete_count,
        missing_symbol_count=len(symbols) - complete_count,
        fetched_bar_rows=total_inserted,
        retries_used=retries_used,
        missing_symbols_sample=sorted([s for s in symbols if counts.get(s, 0) < expected_bars])[:25],
    )


def save_report(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def qualified_table(schema: str, table: str) -> str:
    return f"{schema}.{table}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a single trading day with strict validation")
    parser.add_argument("--date", required=True, help="Target trading day YYYY-MM-DD for 1h and 1m bars")
    parser.add_argument("--schema", default="public", help="Destination schema for candle tables")
    parser.add_argument("--min-price", type=float, default=1.0, help="Universe minimum price")
    parser.add_argument("--max-price", type=float, default=20.0, help="Universe maximum price")
    parser.add_argument("--chunk-size", type=int, default=50, help="Symbols per bars request")
    parser.add_argument("--max-retries", type=int, default=2, help="Refetch retries per stage")
    parser.add_argument("--retry-sleep-seconds", type=float, default=0.3, help="Sleep between chunks")
    parser.add_argument("--hour-start", type=int, default=4, help="Hourly window ET start hour (inclusive)")
    parser.add_argument("--hour-end", type=int, default=8, help="Hourly window ET end hour (exclusive)")
    parser.add_argument("--minute-start", type=int, default=8, help="Minute window ET start hour (inclusive)")
    parser.add_argument("--minute-end", type=int, default=12, help="Minute window ET end hour (exclusive)")
    parser.add_argument("--feed", default="sip", help="Alpaca data feed (sip or iex)")
    parser.add_argument("--output-json", help="Path for summary report JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any stage has missing symbols")
    parser.add_argument(
        "--purge-date",
        action="store_true",
        help="Delete existing bars for the target date (1h/1m) and previous day (1d) before fetching",
    )
    args = parser.parse_args()

    schema = parse_schema(args.schema)
    target_day = parse_date(args.date)
    previous_day = get_previous_trading_day(target_day)

    hour_expected = args.hour_end - args.hour_start
    minute_expected = (args.minute_end - args.minute_start) * 60
    if hour_expected <= 0:
        raise ValueError("hour-end must be greater than hour-start")
    if minute_expected <= 0:
        raise ValueError("minute-end must be greater than minute-start")

    logger.info("Target day: %s", target_day)
    logger.info("Daily bars day: %s", previous_day)
    logger.info("Destination schema: %s", schema)
    logger.info(
        "Expected bars per symbol: daily=1, hourly=%s (%s-%s ET), minute=%s (%s-%s ET)",
        hour_expected,
        args.hour_start,
        args.hour_end,
        minute_expected,
        args.minute_start,
        args.minute_end,
    )
    logger.info("Alpaca feed: %s", args.feed)

    all_symbols = get_all_tradable_stocks()
    priced = get_stocks_in_price_range(
        all_symbols,
        min_price=args.min_price,
        max_price=args.max_price,
        chunk_size=500,
    )
    symbols = sorted({item["symbol"] for item in priced})
    logger.info("Universe symbols in range $%s-$%s: %s", args.min_price, args.max_price, len(symbols))
    if not symbols:
        raise RuntimeError("No symbols returned in price range; cannot continue")

    client = StockHistoricalDataClient(Config.ALPACA_API_KEY, Config.ALPACA_SECRET_KEY)
    stage_results: List[StageResult] = []

    with StockDataDB() as db:
        if args.purge_date:
            logger.warning("Purging existing bars for a clean re-fetch...")
            cursor = db.conn.cursor()
            cursor.execute(
                f"""
                DELETE FROM {qualified_table(schema, "stock_candles_1d")}
                WHERE (time AT TIME ZONE 'America/New_York')::date = %s::date
                """,
                (previous_day,),
            )
            cursor.execute(
                f"""
                DELETE FROM {qualified_table(schema, "stock_candles_1h")}
                WHERE (time AT TIME ZONE 'America/New_York')::date = %s::date
                """,
                (target_day,),
            )
            cursor.execute(
                f"""
                DELETE FROM {qualified_table(schema, "stock_candles_1m")}
                WHERE (time AT TIME ZONE 'America/New_York')::date = %s::date
                """,
                (target_day,),
            )
            db.conn.commit()
            cursor.close()
            logger.warning("Purge complete.")

        stage_results.append(
            run_stage_with_retries(
                stage_name="daily_previous_day",
                client=client,
                db=db,
                symbols=symbols,
                table_name=qualified_table(schema, "stock_candles_1d"),
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                fetch_start=to_et_datetime(previous_day, 0),
                fetch_end=to_et_datetime(target_day, 0),
                validate_date=previous_day,
                expected_bars=1,
                validate_start_hour=None,
                validate_end_hour=None,
                feed=args.feed,
                chunk_size=args.chunk_size,
                max_retries=args.max_retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
            )
        )

        stage_results.append(
            run_stage_with_retries(
                stage_name="hourly_target_day",
                client=client,
                db=db,
                symbols=symbols,
                table_name=qualified_table(schema, "stock_candles_1h"),
                timeframe=TimeFrame(1, TimeFrameUnit.Hour),
                fetch_start=to_et_datetime(target_day, args.hour_start),
                fetch_end=to_et_datetime(target_day, args.hour_end),
                validate_date=target_day,
                expected_bars=hour_expected,
                validate_start_hour=args.hour_start,
                validate_end_hour=args.hour_end,
                feed=args.feed,
                chunk_size=args.chunk_size,
                max_retries=args.max_retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
            )
        )

        stage_results.append(
            run_stage_with_retries(
                stage_name="minute_target_day",
                client=client,
                db=db,
                symbols=symbols,
                table_name=qualified_table(schema, "stock_candles_1m"),
                timeframe=TimeFrame(1, TimeFrameUnit.Minute),
                fetch_start=to_et_datetime(target_day, args.minute_start),
                fetch_end=to_et_datetime(target_day, args.minute_end),
                validate_date=target_day,
                expected_bars=minute_expected,
                validate_start_hour=args.minute_start,
                validate_end_hour=args.minute_end,
                feed=args.feed,
                chunk_size=args.chunk_size,
                max_retries=args.max_retries,
                retry_sleep_seconds=args.retry_sleep_seconds,
            )
        )

    logger.info("")
    logger.info("Summary")
    logger.info("=" * 80)
    for result in stage_results:
        logger.info(
            "%s: complete=%s/%s missing=%s retries_used=%s fetched_rows=%s",
            result.stage,
            result.complete_symbol_count,
            result.target_symbol_count,
            result.missing_symbol_count,
            result.retries_used,
            result.fetched_bar_rows,
        )

    any_missing = any(result.missing_symbol_count > 0 for result in stage_results)
    summary = {
        "target_day": target_day.isoformat(),
        "daily_reference_day": previous_day.isoformat(),
        "schema": schema,
        "price_range": {"min": args.min_price, "max": args.max_price},
        "symbol_count": len(symbols),
        "stages": [asdict(result) for result in stage_results],
        "is_fully_complete": not any_missing,
    }

    output_json = args.output_json or os.path.join(
        os.path.dirname(__file__),
        "..",
        "database",
        "audit_reports",
        f"single_day_bootstrap_{target_day.isoformat()}.json",
    )
    output_json = os.path.abspath(output_json)
    save_report(output_json, summary)
    logger.info("Wrote report: %s", output_json)

    if args.strict and any_missing:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n[STOPPED] Cancelled by user")
