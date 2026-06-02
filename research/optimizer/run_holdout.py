"""
run_holdout.py — Run the best Optuna trial params on a holdout date range.

Waits for the optimizer study to finish (or uses current best), then runs
simulate_one.run_date_range with those params on unseen data.

Usage:
    python research/optimizer/run_holdout.py \
        --study mega_120params_v3 \
        --start 2024-01-02 --end 2024-11-29 \
        --cache-data --cache-dir data/cache
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath('research'))
sys.path.insert(0, os.path.abspath('production'))

import argparse
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from optimizer.run_config import RunConfig
from optimizer.simulate_one import run_date_range
from simulator.simulation_engine import load_memory_cache
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--study',     required=True, help='Optuna study name')
    parser.add_argument('--storage',   default='sqlite:///research/optimizer/optuna.db')
    parser.add_argument('--start',     required=True)
    parser.add_argument('--end',       required=True)
    parser.add_argument('--trial',     type=int, default=None, help='Specific trial # (default: best)')
    parser.add_argument('--cache-data', action='store_true')
    parser.add_argument('--cache-dir',  default='data/cache')
    parser.add_argument('--account',    type=float, default=5000)
    args = parser.parse_args()

    # Load memory cache if available (speeds up sim dramatically)
    if args.cache_data:
        cache_dir = Path(args.cache_dir)
        mc_path = str(cache_dir / 'memory_cache.pkl')
        n = load_memory_cache(mc_path)
        if n:
            print(f"[CACHE] Loaded {n} days from memory cache")
        else:
            print(f"[CACHE] No memory cache found — will load from parquet/DB")

    # Load study and best (or specified) trial
    study = optuna.load_study(study_name=args.study, storage=args.storage)
    if args.trial is not None:
        trial = next(t for t in study.trials if t.number == args.trial)
    else:
        trial = study.best_trial

    print(f"\nStudy      : {args.study}")
    print(f"Best trial : #{trial.number}  in-sample objective = {trial.value:,.1f}")
    print(f"Holdout    : {args.start} -> {args.end}")
    print(f"Account    : ${args.account:,.0f}\n")

    # Rebuild RunConfig from trial params
    from optimizer.optuna_run import _build_config_from_trial
    import types
    # Create a mock trial-like object compatible with _build_config_from_trial
    # by using a fresh Optuna trial from a temp in-memory study
    tmp_study = optuna.create_study(direction='maximize')

    def suggest_from_params(trial_obj):
        """Re-suggest all params using the best trial's fixed values."""
        fixed = trial.params
        class FixedTrial:
            def __init__(self):
                self.params = {}
                self.number = trial.number
            def suggest_float(self, name, low, high, **kw):
                v = fixed.get(name, (low + high) / 2)
                self.params[name] = v
                return v
            def suggest_int(self, name, low, high, **kw):
                v = fixed.get(name, (low + high) // 2)
                self.params[name] = v
                return v
            def suggest_categorical(self, name, choices, **kw):
                v = fixed.get(name, choices[0])
                self.params[name] = v
                return v
        return FixedTrial()

    fixed_trial = suggest_from_params(None)
    cfg = _build_config_from_trial(fixed_trial, mode='full')
    cfg.account_size = args.account

    # Run holdout
    cache_dir = Path(args.cache_dir) if args.cache_data else None
    result = run_date_range(
        cfg,
        start_date=args.start,
        end_date=args.end,
        verbose=False,
        cache_data=args.cache_data,
        cache_dir=str(cache_dir) if cache_dir else None,
        print_dates=True,
        early_abort_days=0,  # never abort — want full holdout picture
    )

    # Print results
    print(f"\n{'='*60}")
    print(f"HOLDOUT RESULTS: {args.start} -> {args.end}")
    print(f"{'='*60}")
    if result['total_trades'] == 0:
        print("No trades taken — config too restrictive for this period.")
        return

    print(f"Total P&L     : ${result['total_pnl']:>10,.2f}")
    print(f"Win rate      : {result['win_rate']:>9.1f}%")
    print(f"Total trades  : {result['total_trades']:>9d}")
    print(f"Days traded   : {result['days_traded']:>9d}")
    print(f"Avg daily P&L : ${result['avg_daily_pnl']:>9,.2f}")
    print(f"Max drawdown  : ${result['max_drawdown']:>9,.2f}")
    print(f"Profit factor : {result['profit_factor']:>9.2f}")
    print(f"Objective     : {result['objective']:>9.1f}")
    print(f"{'='*60}")

    # Compare vs in-sample
    print(f"\nIn-sample objective : {trial.value:,.1f}")
    print(f"Holdout  objective  : {result['objective']:,.1f}")
    ratio = result['objective'] / trial.value if trial.value else 0
    print(f"Holdout/in-sample   : {ratio:.1%}  {'(good — minimal overfit)' if ratio > 0.5 else '(WARNING: likely overfit)'}")


if __name__ == '__main__':
    main()
