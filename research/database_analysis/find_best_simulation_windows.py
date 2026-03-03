#!/usr/bin/env python3
"""
Find the best contiguous window of days for simulations based on coverage.

Criteria (per day):
- Per-symbol minute/hour counts must meet a coverage threshold.
- At least a minimum number of symbols meet those thresholds.

Reports:
- Per-day summary stats
- Best contiguous windows across trading days
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Tuple

from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from utils.query_helpers import StockDataDB  # noqa: E402
from utils.trading_calendar import get_trading_days  # noqa: E402

load_dotenv()


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_schema(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid schema name: {value!r}")
    return value


@dataclass
class DayStats:
    trade_date: date
    symbols_with_both: int
    good_symbols: int
    minute_ratio: float
    hour_ratio: float


@dataclass
class WindowStats:
    start_date: date
    end_date: date
    length: int
    avg_good_symbols: float
    min_good_symbols: int
    avg_minute_ratio: float
    avg_hour_ratio: float


def fetch_day_stats(
    *,
    schema: str,
    minute_start: int,
    minute_end: int,
    hour_start: int,
    hour_end: int,
    min_ratio: float,
) -> List[DayStats]:
    minute_expected = (minute_end - minute_start) * 60
    hour_expected = hour_end - hour_start
    if minute_expected <= 0:
        raise ValueError("minute-end must be greater than minute-start")
    if hour_expected <= 0:
        raise ValueError("hour-end must be greater than hour-start")

    minute_min = int(minute_expected * min_ratio)
    hour_min = int(hour_expected * min_ratio)

    query = f"""
        WITH minute_counts AS (
            SELECT
                (time AT TIME ZONE 'America/New_York')::date AS trade_date,
                symbol,
                COUNT(*)::int AS minute_cnt
            FROM {schema}.stock_candles_1m
            WHERE EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            GROUP BY trade_date, symbol
        ),
        hour_counts AS (
            SELECT
                (time AT TIME ZONE 'America/New_York')::date AS trade_date,
                symbol,
                COUNT(*)::int AS hour_cnt
            FROM {schema}.stock_candles_1h
            WHERE EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            GROUP BY trade_date, symbol
        ),
        joined AS (
            SELECT
                m.trade_date,
                m.symbol,
                m.minute_cnt,
                h.hour_cnt
            FROM minute_counts m
            JOIN hour_counts h
              ON m.trade_date = h.trade_date
             AND m.symbol = h.symbol
        )
        SELECT
            trade_date,
            COUNT(*) AS symbols_with_both,
            COUNT(*) FILTER (
                WHERE minute_cnt >= %s AND hour_cnt >= %s
            ) AS good_symbols,
            SUM(minute_cnt)::float AS minute_total,
            SUM(hour_cnt)::float AS hour_total
        FROM joined
        GROUP BY trade_date
        ORDER BY trade_date
    """

    with StockDataDB() as db:
        cursor = db.conn.cursor()
        cursor.execute(
            query,
            (
                minute_start,
                minute_end,
                hour_start,
                hour_end,
                minute_min,
                hour_min,
            ),
        )
        rows = cursor.fetchall()
        cursor.close()

    stats: List[DayStats] = []
    for trade_date, symbols_with_both, good_symbols, minute_total, hour_total in rows:
        if symbols_with_both == 0:
            continue
        minute_ratio = minute_total / (symbols_with_both * minute_expected)
        hour_ratio = hour_total / (symbols_with_both * hour_expected)
        stats.append(
            DayStats(
                trade_date=trade_date,
                symbols_with_both=int(symbols_with_both),
                good_symbols=int(good_symbols),
                minute_ratio=float(minute_ratio),
                hour_ratio=float(hour_ratio),
            )
        )
    return stats


def build_trading_day_index(stats: List[DayStats]) -> Dict[date, DayStats]:
    return {s.trade_date: s for s in stats}


def find_best_windows(
    stats: List[DayStats],
    *,
    min_good_symbols: int,
    window_days: int | None = None,
    rank_by_completion: bool = False,
) -> List[WindowStats]:
    if not stats:
        return []

    stats_by_date = build_trading_day_index(stats)
    trading_days = get_trading_days(stats[0].trade_date, stats[-1].trade_date)

    windows: List[WindowStats] = []
    if window_days is None:
        current: List[DayStats] = []
        for day in trading_days:
            day_stats = stats_by_date.get(day)
            if day_stats and day_stats.good_symbols >= min_good_symbols:
                current.append(day_stats)
            else:
                if current:
                    windows.append(summarize_window(current))
                    current = []
        if current:
            windows.append(summarize_window(current))
    else:
        indexed: List[Tuple[date, DayStats | None]] = [
            (d, stats_by_date.get(d)) for d in trading_days
        ]
        if len(indexed) >= window_days:
            for i in range(0, len(indexed) - window_days + 1):
                chunk = indexed[i : i + window_days]
                # Only keep windows with complete data for each day.
                if any(item[1] is None for item in chunk):
                    continue
                day_stats = [item[1] for item in chunk if item[1] is not None]
                if any(s.good_symbols < min_good_symbols for s in day_stats):
                    continue
                windows.append(summarize_window(day_stats))

    if rank_by_completion:
        windows.sort(
            key=lambda w: ((w.avg_minute_ratio + w.avg_hour_ratio) / 2, w.avg_good_symbols),
            reverse=True,
        )
    else:
        windows.sort(key=lambda w: (w.length, w.avg_good_symbols), reverse=True)
    return windows


def summarize_window(days: List[DayStats]) -> WindowStats:
    length = len(days)
    avg_good_symbols = sum(d.good_symbols for d in days) / length
    min_good_symbols = min(d.good_symbols for d in days)
    avg_minute_ratio = sum(d.minute_ratio for d in days) / length
    avg_hour_ratio = sum(d.hour_ratio for d in days) / length
    return WindowStats(
        start_date=days[0].trade_date,
        end_date=days[-1].trade_date,
        length=length,
        avg_good_symbols=avg_good_symbols,
        min_good_symbols=min_good_symbols,
        avg_minute_ratio=avg_minute_ratio,
        avg_hour_ratio=avg_hour_ratio,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Find best contiguous window for simulations")
    parser.add_argument("--schema", default="public", help="Schema with candle tables")
    parser.add_argument("--min-coverage", type=float, default=0.80, help="Per-symbol coverage ratio")
    parser.add_argument("--min-symbols", type=int, default=3000, help="Minimum good symbols per day")
    parser.add_argument("--minute-start", type=int, default=8, help="Minute window ET start hour")
    parser.add_argument("--minute-end", type=int, default=12, help="Minute window ET end hour")
    parser.add_argument("--hour-start", type=int, default=4, help="Hour window ET start hour")
    parser.add_argument("--hour-end", type=int, default=8, help="Hour window ET end hour")
    parser.add_argument("--top-days", type=int, default=10, help="Show top N days by good symbols")
    parser.add_argument("--top-windows", type=int, default=5, help="Show top N windows")
    parser.add_argument(
        "--window-days",
        type=int,
        help="If set, only evaluate contiguous windows of this length",
    )
    parser.add_argument(
        "--rank-by-completion",
        action="store_true",
        help="Rank windows by average completion rate instead of length/volume",
    )
    args = parser.parse_args()

    schema = parse_schema(args.schema)
    stats = fetch_day_stats(
        schema=schema,
        minute_start=args.minute_start,
        minute_end=args.minute_end,
        hour_start=args.hour_start,
        hour_end=args.hour_end,
        min_ratio=args.min_coverage,
    )

    if not stats:
        print("No day stats found. Check schema or data availability.")
        return

    stats.sort(key=lambda s: s.trade_date)
    windows = find_best_windows(
        stats,
        min_good_symbols=args.min_symbols,
        window_days=args.window_days,
        rank_by_completion=args.rank_by_completion,
    )

    print("Top days by good symbols")
    top_days = sorted(stats, key=lambda s: s.good_symbols, reverse=True)[: args.top_days]
    for s in top_days:
        print(
            f"{s.trade_date} good={s.good_symbols} "
            f"both={s.symbols_with_both} "
            f"minute_ratio={s.minute_ratio:.2%} hour_ratio={s.hour_ratio:.2%}"
        )

    print("")
    if args.window_days:
        print(f"Top windows (length={args.window_days})")
    else:
        print("Top windows")
    for w in windows[: args.top_windows]:
        print(
            f"{w.start_date} -> {w.end_date} "
            f"days={w.length} "
            f"avg_good={w.avg_good_symbols:.0f} "
            f"min_good={w.min_good_symbols} "
            f"avg_minute_ratio={w.avg_minute_ratio:.2%} "
            f"avg_hour_ratio={w.avg_hour_ratio:.2%}"
        )


if __name__ == "__main__":
    main()
