"""
run_oracle_study.py — Optimize ONE temperature regime on its TRAIN days.

Part of the market-temperature oracle test. Runs an Optuna study over the
ground-truth-labeled training days for a single regime (or the universal
baseline) and stores results in shared, resumable storage.

    python optimizer/run_oracle_study.py --regime universal --trials 300
    python optimizer/run_oracle_study.py --regime hot       --trials 300
    python optimizer/run_oracle_study.py --regime neutral   --trials 300
    python optimizer/run_oracle_study.py --regime cold       --trials 300

Run UNIVERSAL first (it is the baseline the regime configs must beat), then the
three regimes — one after another, NOT simultaneously (single Postgres DB +
RAM ceiling; the Phase-1 backfill must already be finished).

Each study writes to:
    --optuna-db  (default sqlite:///optimizer/oracle_optuna.db)  study=oracle_<regime>
    --db         (default optimizer/oracle_results.db)           run_id=oracle_<regime>_NNNNN

Studies are resumable: re-running with the same --regime continues where it left
off until --trials total is reached.

Use run_oracle_test.py to drive all four sequentially + run the held-out evaluation.
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))            # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import argparse

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna tqdm")
    sys.exit(1)

from optimizer.results_db import init_db
from optimizer.optuna_run import _Heartbeat
from optimizer.oracle_objective import make_oracle_objective
from optimizer.oracle_labels import load_oracle_sets, summarize, REGIMES

DEFAULT_OPTUNA_DB = 'sqlite:///optimizer/oracle_optuna.db'
DEFAULT_RESULTS_DB = 'optimizer/oracle_results.db'


def run_oracle_study(
    regime: str,
    n_trials: int = 300,
    test_frac: float = 0.30,
    outputs_dir: str | None = None,
    optuna_db_url: str | None = None,
    results_db_path: str | None = None,
    mode: str = 'full',
    debug: bool = False,
    cache_data: bool = False,
    cache_dir: str | None = None,
    oracle_sets=None,
) -> optuna.Study:
    """Optimize a single regime on its TRAIN days. Returns the Optuna study."""
    regime = regime.lower()
    valid = REGIMES + ('universal',)
    if regime not in valid:
        raise ValueError(f"--regime must be one of {valid}, got {regime!r}")

    sets = oracle_sets or load_oracle_sets(outputs_dir, test_frac)
    train_days = sets.days_for(regime, 'train')
    if not train_days:
        raise ValueError(f"No TRAIN days for regime '{regime}'. Check the label CSVs / test_frac.")

    storage = optuna_db_url or DEFAULT_OPTUNA_DB
    results_conn = init_db(results_db_path or DEFAULT_RESULTS_DB)
    study_name = f'oracle_{regime}'

    study = optuna.create_study(
        study_name=study_name,
        direction='maximize',
        storage=storage,
        load_if_exists=True,
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_warmup_steps=0),
    )

    n_existing = len(study.trials)
    n_remaining = max(0, n_trials - n_existing)

    print(f"\n{'='*60}")
    print(f"Oracle study : {study_name}")
    print(f"Train days   : {len(train_days)} "
          f"({train_days[0]} .. {train_days[-1]})")
    print(f"Trials       : {n_trials} total ({n_existing} done, {n_remaining} to run)")
    print(f"Optuna DB    : {storage}")
    print(f"Results DB   : {results_db_path or DEFAULT_RESULTS_DB}")
    print(f"Mode         : {mode}")
    print(f"{'='*60}\n")

    if n_remaining == 0:
        print("All trials already complete for this regime.")
    else:
        heartbeat = _Heartbeat(interval=30)
        objective = make_oracle_objective(
            regime=regime,
            train_days=train_days,
            results_conn=results_conn,
            mode=mode,
            debug=debug,
            cache_data=cache_data,
            cache_dir=cache_dir,
            heartbeat=heartbeat,
        )
        heartbeat.start()
        try:
            study.optimize(objective, n_trials=n_remaining, show_progress_bar=True)
        finally:
            heartbeat.stop()

    results_conn.close()

    # study.best_trial RAISES (ValueError) when no trial has completed — e.g. every
    # trial pruned because a thin regime produced 0 trades. Guard it.
    try:
        best = study.best_trial
        print(f"\n  [{regime}] best trial #{best.number}: "
              f"objective = ${best.value:,.0f}")
    except ValueError:
        print(f"\n  [{regime}] WARNING: no completed trials (all pruned / 0 trades). "
              f"Check this regime has enough days with data.")
    return study


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Optimize one market-temperature regime (oracle test)')
    ap.add_argument('--regime', required=True, choices=list(REGIMES) + ['universal'])
    ap.add_argument('--trials', type=int, default=300)
    ap.add_argument('--test-frac', type=float, default=0.30,
                    help='Held-out fraction (chronological). MUST match across all regimes.')
    ap.add_argument('--outputs-dir', default=None, help='Dir with hot/neutral/cold_days.csv')
    ap.add_argument('--optuna-db', default=None, help=f'Optuna storage URL (default {DEFAULT_OPTUNA_DB})')
    ap.add_argument('--db', default=None, help=f'Results SQLite path (default {DEFAULT_RESULTS_DB})')
    ap.add_argument('--mode', default='full', choices=['full', 'gates-only', 'single-indicator'])
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--cache-data', action='store_true')
    ap.add_argument('--cache-dir', default='data/cache')
    args = ap.parse_args()

    # Show the split once up front so the user can sanity-check counts.
    sets = load_oracle_sets(args.outputs_dir, args.test_frac)
    print("Oracle day-label split:")
    print(summarize(sets))

    run_oracle_study(
        regime=args.regime,
        n_trials=args.trials,
        test_frac=args.test_frac,
        outputs_dir=args.outputs_dir,
        optuna_db_url=args.optuna_db,
        results_db_path=args.db,
        mode=args.mode,
        debug=args.debug,
        cache_data=args.cache_data,
        cache_dir=args.cache_dir if args.cache_data else None,
        oracle_sets=sets,
    )
