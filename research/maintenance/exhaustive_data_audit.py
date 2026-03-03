#!/usr/bin/env python3
"""
Exhaustive Data Audit
=====================

Audits minute/hour/daily table consistency for every NYSE trading day in a range.

Checks performed:
1) Minute data (8:00-12:00 ET)
   - Per-symbol bar count consistency (expected: 240 bars)
   - Gap extraction (missing windows per symbol)
   - Day-level stats: symbol count, min/max price, symbols outside $1-$20

2) Hour data (4:00-8:00 ET)
   - Per-symbol bar count consistency (expected: 4 bars)
   - Gap extraction (missing windows per symbol)
   - Day-level stats: symbol count, min/max price, symbols outside $1-$20

3) Daily data
   - Per-symbol bar count consistency (expected: 1 bar)
   - Day-level stats: symbol count, min/max price, symbols outside $1-$20

4) Cross-table symbol-set alignment
   - Per-day set differences between minute/hour/daily symbols

Outputs (CSV):
  audit_day_summary.csv
  audit_symbol_set_diff.csv
  audit_minute_missing_symbol_days.csv
  audit_minute_missing_windows.csv
  audit_hour_missing_symbol_days.csv
  audit_hour_missing_windows.csv
  audit_daily_missing_symbol_days.csv

Usage:
  python maintenance/exhaustive_data_audit.py
  python maintenance/exhaustive_data_audit.py --start 2024-12-01 --end 2026-02-23
  python maintenance/exhaustive_data_audit.py --no-windows
"""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from utils.query_helpers import StockDataDB
from utils.trading_calendar import get_trading_days


# Expected bars per symbol per day for each interval window
EXPECTED_MINUTE_BARS = 240  # 8:00-11:59 ET
EXPECTED_HOUR_BARS = 4      # 4:00,5:00,6:00,7:00 ET
EXPECTED_DAILY_BARS = 1


@dataclass
class DayCoverage:
    symbols_total: int
    symbols_complete: int
    symbols_with_gaps: int
    bars_total: int
    min_price: float | None
    max_price: float | None
    symbols_outside_1_20: int


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _write_csv(path: str, headers: List[str], rows: Iterable[dict]) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _price_range_and_outside_count(
    db: StockDataDB,
    table: str,
    trade_date: date,
    start_hour: int | None = None,
    end_hour: int | None = None,
) -> Tuple[float | None, float | None, int]:
    cursor = db.conn.cursor()
    if table in ('stock_candles_1m', 'stock_candles_1h'):
        cursor.execute(
            f"""
            SELECT
                MIN(low)::float,
                MAX(high)::float,
                COUNT(DISTINCT symbol) FILTER (WHERE low < 1 OR high > 20)
            FROM {table}
            WHERE time::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            """,
            (trade_date, start_hour, end_hour),
        )
    else:
        cursor.execute(
            f"""
            SELECT
                MIN(low)::float,
                MAX(high)::float,
                COUNT(DISTINCT symbol) FILTER (WHERE low < 1 OR high > 20)
            FROM {table}
            WHERE time::date = %s::date
            """,
            (trade_date,),
        )
    row = cursor.fetchone()
    cursor.close()
    return row[0], row[1], int(row[2] or 0)


def _symbol_counts_for_window(
    db: StockDataDB,
    table: str,
    trade_date: date,
    start_hour: int | None = None,
    end_hour: int | None = None,
) -> Dict[str, int]:
    cursor = db.conn.cursor()
    if table in ('stock_candles_1m', 'stock_candles_1h'):
        cursor.execute(
            f"""
            SELECT symbol, COUNT(*)::int
            FROM {table}
            WHERE time::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
            GROUP BY symbol
            """,
            (trade_date, start_hour, end_hour),
        )
    else:
        cursor.execute(
            f"""
            SELECT symbol, COUNT(*)::int
            FROM {table}
            WHERE time::date = %s::date
            GROUP BY symbol
            """,
            (trade_date,),
        )
    rows = cursor.fetchall()
    cursor.close()
    return {symbol: cnt for symbol, cnt in rows}


def _symbols_for_window(
    db: StockDataDB,
    table: str,
    trade_date: date,
    start_hour: int | None = None,
    end_hour: int | None = None,
) -> set[str]:
    return set(_symbol_counts_for_window(db, table, trade_date, start_hour, end_hour).keys())


def _missing_timestamps_for_symbol(
    db: StockDataDB,
    table: str,
    symbol: str,
    trade_date: date,
    start_hour: int,
    end_hour: int,
    interval: str,
) -> List[datetime]:
    """
    Return missing UTC timestamps for one symbol in one day/window.
    interval: '1 minute' or '1 hour'
    """
    cursor = db.conn.cursor()

    trunc_unit = 'minute' if interval == '1 minute' else 'hour'
    cursor.execute(
        f"""
        WITH bounds AS (
            SELECT
                ((%s::date + make_time(%s, 0, 0)) AT TIME ZONE 'America/New_York') AS start_utc,
                ((%s::date + make_time(%s, 0, 0)) AT TIME ZONE 'America/New_York') AS end_utc
        ),
        expected AS (
            SELECT generate_series(
                (SELECT start_utc FROM bounds),
                (SELECT end_utc FROM bounds) - %s::interval,
                %s::interval
            ) AS ts
        ),
        actual AS (
            SELECT DISTINCT date_trunc('{trunc_unit}', time) AS ts
            FROM {table}
            WHERE symbol = %s
              AND time::date = %s::date
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') >= %s
              AND EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') < %s
        )
        SELECT e.ts
        FROM expected e
        LEFT JOIN actual a ON a.ts = e.ts
        WHERE a.ts IS NULL
        ORDER BY e.ts
        """,
        (trade_date, start_hour, trade_date, end_hour, interval, interval, symbol, trade_date, start_hour, end_hour),
    )
    rows = cursor.fetchall()
    cursor.close()
    return [r[0] for r in rows]


def _compress_missing_windows(missing_ts: List[datetime], step: timedelta) -> List[Tuple[datetime, datetime, int]]:
    if not missing_ts:
        return []
    windows = []
    start = missing_ts[0]
    prev = missing_ts[0]
    count = 1
    for ts in missing_ts[1:]:
        if ts - prev == step:
            prev = ts
            count += 1
            continue
        windows.append((start, prev, count))
        start = ts
        prev = ts
        count = 1
    windows.append((start, prev, count))
    return windows


def _build_day_coverage(
    counts: Dict[str, int],
    expected: int,
    bars_total: int,
    min_price: float | None,
    max_price: float | None,
    outside_count: int,
) -> DayCoverage:
    symbols_total = len(counts)
    symbols_complete = sum(1 for v in counts.values() if v == expected)
    symbols_with_gaps = sum(1 for v in counts.values() if v < expected)
    return DayCoverage(
        symbols_total=symbols_total,
        symbols_complete=symbols_complete,
        symbols_with_gaps=symbols_with_gaps,
        bars_total=bars_total,
        min_price=min_price,
        max_price=max_price,
        symbols_outside_1_20=outside_count,
    )


def run_audit(start_date: date, end_date: date, output_dir: str, include_windows: bool) -> None:
    _ensure_dir(output_dir)

    trading_days = get_trading_days(start_date, end_date)
    print(f"Trading days to audit: {len(trading_days)} ({start_date} -> {end_date})")

    day_summary_rows: List[dict] = []
    symbol_set_diff_rows: List[dict] = []
    minute_missing_symbol_rows: List[dict] = []
    minute_missing_window_rows: List[dict] = []
    hour_missing_symbol_rows: List[dict] = []
    hour_missing_window_rows: List[dict] = []
    daily_missing_symbol_rows: List[dict] = []

    with StockDataDB() as db:
        for idx, d in enumerate(trading_days, start=1):
            print(f"[{idx}/{len(trading_days)}] Auditing {d} ...")

            minute_counts = _symbol_counts_for_window(db, 'stock_candles_1m', d, 8, 12)
            hour_counts = _symbol_counts_for_window(db, 'stock_candles_1h', d, 4, 8)
            daily_counts = _symbol_counts_for_window(db, 'stock_candles_1d', d)

            minute_min_price, minute_max_price, minute_outside = _price_range_and_outside_count(
                db, 'stock_candles_1m', d, 8, 12
            )
            hour_min_price, hour_max_price, hour_outside = _price_range_and_outside_count(
                db, 'stock_candles_1h', d, 4, 8
            )
            daily_min_price, daily_max_price, daily_outside = _price_range_and_outside_count(
                db, 'stock_candles_1d', d
            )

            minute_cov = _build_day_coverage(
                minute_counts,
                EXPECTED_MINUTE_BARS,
                sum(minute_counts.values()),
                minute_min_price,
                minute_max_price,
                minute_outside,
            )
            hour_cov = _build_day_coverage(
                hour_counts,
                EXPECTED_HOUR_BARS,
                sum(hour_counts.values()),
                hour_min_price,
                hour_max_price,
                hour_outside,
            )
            daily_cov = _build_day_coverage(
                daily_counts,
                EXPECTED_DAILY_BARS,
                sum(daily_counts.values()),
                daily_min_price,
                daily_max_price,
                daily_outside,
            )

            day_summary_rows.append({
                'date': d.isoformat(),
                'minute_symbols': minute_cov.symbols_total,
                'minute_complete_symbols': minute_cov.symbols_complete,
                'minute_gap_symbols': minute_cov.symbols_with_gaps,
                'minute_total_bars': minute_cov.bars_total,
                'minute_min_price': minute_cov.min_price,
                'minute_max_price': minute_cov.max_price,
                'minute_symbols_outside_1_20': minute_cov.symbols_outside_1_20,
                'hour_symbols': hour_cov.symbols_total,
                'hour_complete_symbols': hour_cov.symbols_complete,
                'hour_gap_symbols': hour_cov.symbols_with_gaps,
                'hour_total_bars': hour_cov.bars_total,
                'hour_min_price': hour_cov.min_price,
                'hour_max_price': hour_cov.max_price,
                'hour_symbols_outside_1_20': hour_cov.symbols_outside_1_20,
                'daily_symbols': daily_cov.symbols_total,
                'daily_complete_symbols': daily_cov.symbols_complete,
                'daily_gap_symbols': daily_cov.symbols_with_gaps,
                'daily_total_bars': daily_cov.bars_total,
                'daily_min_price': daily_cov.min_price,
                'daily_max_price': daily_cov.max_price,
                'daily_symbols_outside_1_20': daily_cov.symbols_outside_1_20,
            })

            minute_syms = set(minute_counts.keys())
            hour_syms = set(hour_counts.keys())
            daily_syms = set(daily_counts.keys())

            symbol_set_diff_rows.append({
                'date': d.isoformat(),
                'minute_symbols': len(minute_syms),
                'hour_symbols': len(hour_syms),
                'daily_symbols': len(daily_syms),
                'minute_not_in_hour': len(minute_syms - hour_syms),
                'minute_not_in_daily': len(minute_syms - daily_syms),
                'hour_not_in_minute': len(hour_syms - minute_syms),
                'hour_not_in_daily': len(hour_syms - daily_syms),
                'daily_not_in_minute': len(daily_syms - minute_syms),
                'daily_not_in_hour': len(daily_syms - hour_syms),
                'minute_not_in_hour_sample': ','.join(sorted(list(minute_syms - hour_syms))[:10]),
                'hour_not_in_minute_sample': ','.join(sorted(list(hour_syms - minute_syms))[:10]),
                'daily_not_in_minute_sample': ','.join(sorted(list(daily_syms - minute_syms))[:10]),
            })

            for sym, observed in minute_counts.items():
                if observed < EXPECTED_MINUTE_BARS:
                    minute_missing_symbol_rows.append({
                        'date': d.isoformat(),
                        'symbol': sym,
                        'observed_bars': observed,
                        'expected_bars': EXPECTED_MINUTE_BARS,
                        'missing_bars': EXPECTED_MINUTE_BARS - observed,
                    })
                    if include_windows:
                        missing = _missing_timestamps_for_symbol(
                            db, 'stock_candles_1m', sym, d, 8, 12, '1 minute'
                        )
                        windows = _compress_missing_windows(missing, timedelta(minutes=1))
                        for w_start, w_end, count in windows:
                            minute_missing_window_rows.append({
                                'date': d.isoformat(),
                                'symbol': sym,
                                'start_utc': w_start.isoformat(),
                                'end_utc': w_end.isoformat(),
                                'missing_bars': count,
                            })

            for sym, observed in hour_counts.items():
                if observed < EXPECTED_HOUR_BARS:
                    hour_missing_symbol_rows.append({
                        'date': d.isoformat(),
                        'symbol': sym,
                        'observed_bars': observed,
                        'expected_bars': EXPECTED_HOUR_BARS,
                        'missing_bars': EXPECTED_HOUR_BARS - observed,
                    })
                    if include_windows:
                        missing = _missing_timestamps_for_symbol(
                            db, 'stock_candles_1h', sym, d, 4, 8, '1 hour'
                        )
                        windows = _compress_missing_windows(missing, timedelta(hours=1))
                        for w_start, w_end, count in windows:
                            hour_missing_window_rows.append({
                                'date': d.isoformat(),
                                'symbol': sym,
                                'start_utc': w_start.isoformat(),
                                'end_utc': w_end.isoformat(),
                                'missing_bars': count,
                            })

            for sym, observed in daily_counts.items():
                if observed < EXPECTED_DAILY_BARS:
                    daily_missing_symbol_rows.append({
                        'date': d.isoformat(),
                        'symbol': sym,
                        'observed_bars': observed,
                        'expected_bars': EXPECTED_DAILY_BARS,
                        'missing_bars': EXPECTED_DAILY_BARS - observed,
                    })

    _write_csv(
        os.path.join(output_dir, 'audit_day_summary.csv'),
        [
            'date',
            'minute_symbols', 'minute_complete_symbols', 'minute_gap_symbols', 'minute_total_bars',
            'minute_min_price', 'minute_max_price', 'minute_symbols_outside_1_20',
            'hour_symbols', 'hour_complete_symbols', 'hour_gap_symbols', 'hour_total_bars',
            'hour_min_price', 'hour_max_price', 'hour_symbols_outside_1_20',
            'daily_symbols', 'daily_complete_symbols', 'daily_gap_symbols', 'daily_total_bars',
            'daily_min_price', 'daily_max_price', 'daily_symbols_outside_1_20',
        ],
        day_summary_rows,
    )
    _write_csv(
        os.path.join(output_dir, 'audit_symbol_set_diff.csv'),
        [
            'date',
            'minute_symbols', 'hour_symbols', 'daily_symbols',
            'minute_not_in_hour', 'minute_not_in_daily',
            'hour_not_in_minute', 'hour_not_in_daily',
            'daily_not_in_minute', 'daily_not_in_hour',
            'minute_not_in_hour_sample', 'hour_not_in_minute_sample', 'daily_not_in_minute_sample',
        ],
        symbol_set_diff_rows,
    )
    _write_csv(
        os.path.join(output_dir, 'audit_minute_missing_symbol_days.csv'),
        ['date', 'symbol', 'observed_bars', 'expected_bars', 'missing_bars'],
        minute_missing_symbol_rows,
    )
    _write_csv(
        os.path.join(output_dir, 'audit_hour_missing_symbol_days.csv'),
        ['date', 'symbol', 'observed_bars', 'expected_bars', 'missing_bars'],
        hour_missing_symbol_rows,
    )
    _write_csv(
        os.path.join(output_dir, 'audit_daily_missing_symbol_days.csv'),
        ['date', 'symbol', 'observed_bars', 'expected_bars', 'missing_bars'],
        daily_missing_symbol_rows,
    )

    if include_windows:
        _write_csv(
            os.path.join(output_dir, 'audit_minute_missing_windows.csv'),
            ['date', 'symbol', 'start_utc', 'end_utc', 'missing_bars'],
            minute_missing_window_rows,
        )
        _write_csv(
            os.path.join(output_dir, 'audit_hour_missing_windows.csv'),
            ['date', 'symbol', 'start_utc', 'end_utc', 'missing_bars'],
            hour_missing_window_rows,
        )

    print("\nAudit complete.")
    print(f"Output directory: {output_dir}")
    print(f"Day summary rows: {len(day_summary_rows)}")
    print(f"Minute gap symbol-days: {len(minute_missing_symbol_rows)}")
    print(f"Hour gap symbol-days: {len(hour_missing_symbol_rows)}")
    print(f"Daily gap symbol-days: {len(daily_missing_symbol_rows)}")
    if include_windows:
        print(f"Minute missing windows: {len(minute_missing_window_rows)}")
        print(f"Hour missing windows: {len(hour_missing_window_rows)}")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, '%Y-%m-%d').date()


def main() -> None:
    today = date.today()

    parser = argparse.ArgumentParser(description='Exhaustive OHLCV data audit')
    parser.add_argument('--start', default='2024-12-01', help='Start date YYYY-MM-DD (default: 2024-12-01)')
    parser.add_argument('--end', default=today.isoformat(), help='End date YYYY-MM-DD (default: today)')
    parser.add_argument(
        '--output-dir',
        default=os.path.join(os.path.dirname(__file__), '..', 'database', 'audit_reports'),
        help='Directory for CSV outputs',
    )
    parser.add_argument(
        '--no-windows',
        action='store_true',
        help='Skip per-symbol missing-window extraction (faster)',
    )
    args = parser.parse_args()

    start_date = _parse_date(args.start)
    end_date = _parse_date(args.end)
    if start_date > end_date:
        raise ValueError('start date must be <= end date')

    output_dir = os.path.abspath(args.output_dir)
    run_audit(start_date, end_date, output_dir, include_windows=not args.no_windows)


if __name__ == '__main__':
    main()

