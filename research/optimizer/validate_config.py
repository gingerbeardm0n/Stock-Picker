"""
validate_config.py — Walk-forward validation of a specific trial config.

Loads a trial's exact params from results.db, runs them on a new date range
(data the optimizer never saw), and writes results back to results.db so you
can compare in-sample vs out-of-sample with query_results.py.

Usage:
    # Validate best trial on Dec 2025 (out-of-sample)
    python optimizer/validate_config.py --trial 492 --start 2025-12-01 --end 2025-12-31

    # Validate with a custom gapper universe file
    python optimizer/validate_config.py --trial 492 --start 2025-12-01 --end 2025-12-31 \\
        --symbols-file database/audit_reports/top_100_gaprun_symbols_dec2025.csv

    # Validate multiple trials at once
    python optimizer/validate_config.py --trial 492 488 490 --start 2025-12-01 --end 2025-12-31

    # View results afterwards
    python optimizer/query_results.py --top 30
    python optimizer/query_results.py --trade-detail validate_00492_2025-12-01
"""

from __future__ import annotations
import argparse
import csv
import json
import os
import sqlite3
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from optimizer.run_config import RunConfig
from optimizer.results_db import init_db, write_run
from optimizer.simulate_one import run_date_range


def load_trial_params(db_path: str, trial_id: str) -> tuple[str, dict]:
    """Load params_json for a trial. Returns (run_id, params_dict)."""
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Normalise trial_id
    trial_id = trial_id.strip()
    if not trial_id.startswith('optuna_') and not trial_id.startswith('meta_') and not trial_id.startswith('validate_'):
        try:
            run_id = f'optuna_{int(trial_id):05d}'
        except ValueError:
            run_id = trial_id
    else:
        run_id = trial_id

    cursor.execute('SELECT params_json, total_pnl, total_trades FROM runs WHERE run_id = ?', (run_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        print(f"ERROR: Trial '{run_id}' not found in {db_path}")
        sys.exit(1)

    params_json, original_pnl, original_trades = row
    params = json.loads(params_json) if params_json else {}
    print(f"  Loaded: {run_id}  (original: ${original_pnl:,.0f} P&L, {original_trades} trades)")
    return run_id, params


def validate_trial(
    trial_id: str,
    start_date: str,
    end_date: str,
    db_path: str,
    symbols_file: str | None,
    cache_data: bool,
    cache_dir: str | None,
) -> None:
    print(f"\n{'='*70}")
    print(f"  Validating trial {trial_id}")
    print(f"  Date range : {start_date} -> {end_date}")
    print(f"  Universe   : {symbols_file or 'all stocks (no --symbols-file)'}")
    print(f"{'='*70}")

    # Load original params
    source_run_id, params = load_trial_params(db_path, trial_id)

    # Reconstruct RunConfig from flat dict
    try:
        cfg = RunConfig.from_flat_dict(params)
    except Exception as e:
        print(f"ERROR: Could not reconstruct config from params: {e}")
        sys.exit(1)

    # Load symbol universe if provided (supports flat list or date-specific format)
    symbol_universe: list | dict | None = None
    if symbols_file:
        if not os.path.exists(symbols_file):
            print(f"ERROR: Symbols file not found: {symbols_file}")
            sys.exit(1)
        with open(symbols_file) as f:
            reader = csv.reader(f)
            header = next(reader)
            if header[0].strip().lower() == 'date':
                # DATE-SPECIFIC FORMAT: {date_str: [symbols]}
                universe_dict: dict[str, list] = {}
                for row in reader:
                    if len(row) >= 2:
                        universe_dict.setdefault(row[0].strip(), []).append(row[1].strip())
                symbol_universe = universe_dict
                total = sum(len(v) for v in universe_dict.values())
                print(f"  Symbols    : {total} date-symbol pairs across {len(universe_dict)} dates (date-specific mode)")
            else:
                symbol_universe = [row[0].strip() for row in reader if row]
                print(f"  Symbols    : {len(symbol_universe)} from {symbols_file}")

    # Run simulation on new date range
    print(f"  Running simulation...")
    result = run_date_range(
        cfg,
        start_date,
        end_date,
        verbose=False,
        debug=False,
        cache_data=cache_data,
        cache_dir=cache_dir,
        symbol_universe=symbol_universe,
    )

    if result['total_trades'] == 0:
        print(f"  WARNING: Zero trades — no data for this date range or universe")
        return

    # Write to results.db with a validation run_id
    # Normalise source run_id for the label
    label = source_run_id.replace('optuna_', '').replace('meta_', 'm')
    run_id = f'validate_{label}_{start_date}'

    trades = result.pop('trades')
    conn = init_db(db_path)
    write_run(conn, run_id, start_date, end_date, result, params, trades)
    conn.close()
    result['trades'] = trades  # restore for display

    # Print summary
    print(f"\n  Results ({run_id}):")
    print(f"    P&L        : ${result['total_pnl']:>10,.2f}")
    print(f"    Trades     : {result['total_trades']}")
    print(f"    Win rate   : {result['win_rate']:.1f}%")
    print(f"    Profit factor: {result['profit_factor']:.2f}")
    print(f"    Max drawdown : ${result['max_drawdown']:,.2f}")
    print(f"    Days traded  : {result['days_traded']}")
    print(f"\n  Saved to {db_path} as '{run_id}'")
    print(f"  View trades: python optimizer/query_results.py --trade-detail {run_id}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Walk-forward validation of a specific Optuna trial config'
    )
    parser.add_argument('--trial',        nargs='+', required=True,
                        metavar='ID',
                        help='Trial ID(s) to validate (e.g. 492, 00492, optuna_00492)')
    parser.add_argument('--start',        required=True, help='Validation start date YYYY-MM-DD')
    parser.add_argument('--end',          required=True, help='Validation end date YYYY-MM-DD')
    parser.add_argument('--symbols-file', default=None,
                        help='CSV with symbol universe for validation (col 0 = symbol, has header). '
                             'Omit to run against all stocks using scanner gates from the original config.')
    parser.add_argument('--db',           default='optimizer/results.db',
                        help='Results database path (default: optimizer/results.db)')
    parser.add_argument('--cache-data',   action='store_true',
                        help='Cache market data in memory/disk between days')
    parser.add_argument('--cache-dir',    default='data/cache',
                        help='Directory for cache files (default: data/cache)')
    args = parser.parse_args()

    for trial_id in args.trial:
        validate_trial(
            trial_id=trial_id,
            start_date=args.start,
            end_date=args.end,
            db_path=args.db,
            symbols_file=args.symbols_file,
            cache_data=args.cache_data,
            cache_dir=args.cache_dir if args.cache_data else None,
        )

    print(f"\n{'='*70}")
    print(f"  Done. Run query_results.py to compare in-sample vs out-of-sample.")
    print(f"{'='*70}\n")
