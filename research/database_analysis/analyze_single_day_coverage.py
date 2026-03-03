#!/usr/bin/env python3
"""
Analyze per-symbol bar coverage for a single day in a schema.

Examples:
  python database/analyze_single_day_coverage.py --date 2026-02-20 --schema sandbox --hour-end 9
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime
from typing import Dict, List

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.query_helpers import StockDataDB  # noqa: E402

load_dotenv()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_symbol_counts(
    db: StockDataDB,
    table_name: str,
    symbols: List[str],
    trade_date: date,
    start_hour: int,
    end_hour: int,
) -> Dict[str, int]:
    if not symbols:
        return {}

    cursor = db.conn.cursor()
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


def percentile(sorted_vals: List[int], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if pct <= 0:
        return float(sorted_vals[0])
    if pct >= 100:
        return float(sorted_vals[-1])
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return float(d0 + d1)


def summarize_counts(label: str, counts: List[int], expected: int) -> None:
    if not counts:
        print(f"{label}: no symbols to report")
        return

    sorted_counts = sorted(counts)
    total = len(sorted_counts)
    avg = sum(sorted_counts) / total
    median = percentile(sorted_counts, 50)
    p90 = percentile(sorted_counts, 90)
    p95 = percentile(sorted_counts, 95)
    min_v = sorted_counts[0]
    max_v = sorted_counts[-1]

    def pct_at_least(threshold: int) -> float:
        if threshold <= 0:
            return 100.0
        ok = sum(1 for c in sorted_counts if c >= threshold)
        return ok * 100.0 / total

    print(f"{label}")
    print(f"  expected: {expected}")
    print(f"  symbols:  {total}")
    print(f"  avg:      {avg:.2f}")
    print(f"  median:   {median:.2f}")
    print(f"  p90:      {p90:.2f}")
    print(f"  p95:      {p95:.2f}")
    print(f"  min/max:  {min_v} / {max_v}")
    print(f"  >=100%:   {pct_at_least(expected):.2f}%")
    print(f"  >=90%:    {pct_at_least(int(expected * 0.90)): .2f}%")
    print(f"  >=75%:    {pct_at_least(int(expected * 0.75)): .2f}%")
    print(f"  >=50%:    {pct_at_least(int(expected * 0.50)): .2f}%")
    print("")


def print_coverage_ratio(label: str, counts: List[int], expected: int) -> None:
    total_symbols = len(counts)
    if total_symbols == 0 or expected <= 0:
        print(f"{label} coverage: no data")
        return

    actual_total = sum(counts)
    expected_total = total_symbols * expected
    ratio = (actual_total / expected_total * 100) if expected_total > 0 else 0.0
    print(f"{label} overall: {actual_total}/{expected_total} bars ({ratio:.2f}%)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze single-day coverage ratios")
    parser.add_argument("--date", required=True, help="Target trading day YYYY-MM-DD")
    parser.add_argument("--schema", default="public", help="Schema with candle tables")
    parser.add_argument("--min-price", type=float, default=1.0, help="Universe minimum price")
    parser.add_argument("--max-price", type=float, default=20.0, help="Universe maximum price")
    parser.add_argument(
        "--use-db-symbols",
        action="store_true",
        help="Use distinct symbols from candle tables instead of Alpaca universe",
    )
    parser.add_argument("--hour-start", type=int, default=4, help="Hourly window ET start hour (inclusive)")
    parser.add_argument("--hour-end", type=int, default=8, help="Hourly window ET end hour (exclusive)")
    parser.add_argument("--minute-start", type=int, default=8, help="Minute window ET start hour (inclusive)")
    parser.add_argument("--minute-end", type=int, default=12, help="Minute window ET end hour (exclusive)")
    args = parser.parse_args()

    target_day = parse_date(args.date)
    hour_expected = args.hour_end - args.hour_start
    minute_expected = (args.minute_end - args.minute_start) * 60
    if hour_expected <= 0:
        raise ValueError("hour-end must be greater than hour-start")
    if minute_expected <= 0:
        raise ValueError("minute-end must be greater than minute-start")

    symbols: List[str] = []
    if args.use_db_symbols:
        with StockDataDB() as db:
            cursor = db.conn.cursor()
            cursor.execute(
                f"""
                SELECT DISTINCT symbol
                FROM {args.schema}.stock_candles_1m
                WHERE (time AT TIME ZONE 'America/New_York')::date = %s::date
                UNION
                SELECT DISTINCT symbol
                FROM {args.schema}.stock_candles_1h
                WHERE (time AT TIME ZONE 'America/New_York')::date = %s::date
                ORDER BY symbol
                """,
                (target_day, target_day),
            )
            symbols = [row[0] for row in cursor.fetchall()]
            cursor.close()
    else:
        from services.fetch_stocks_in_price_range import (  # noqa: E402
            get_all_tradable_stocks,
            get_stocks_in_price_range,
        )

        all_symbols = get_all_tradable_stocks()
        priced = get_stocks_in_price_range(
            all_symbols,
            min_price=args.min_price,
            max_price=args.max_price,
            chunk_size=500,
        )
        symbols = sorted({item["symbol"] for item in priced})
    if not symbols:
        raise RuntimeError("No symbols returned in price range; cannot continue")

    with StockDataDB() as db:
        hour_counts = get_symbol_counts(
            db=db,
            table_name=f"{args.schema}.stock_candles_1h",
            symbols=symbols,
            trade_date=target_day,
            start_hour=args.hour_start,
            end_hour=args.hour_end,
        )
        minute_counts = get_symbol_counts(
            db=db,
            table_name=f"{args.schema}.stock_candles_1m",
            symbols=symbols,
            trade_date=target_day,
            start_hour=args.minute_start,
            end_hour=args.minute_end,
        )

    hour_list = [hour_counts.get(sym, 0) for sym in symbols]
    minute_list = [minute_counts.get(sym, 0) for sym in symbols]

    print_coverage_ratio("Hourly", hour_list, hour_expected)
    print_coverage_ratio("Minute", minute_list, minute_expected)

    summarize_counts("Hourly coverage", hour_list, hour_expected)
    summarize_counts("Minute coverage", minute_list, minute_expected)


if __name__ == "__main__":
    main()
