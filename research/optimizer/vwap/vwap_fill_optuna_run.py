"""
vwap_fill_optuna_run.py — VWAP Reclaim re-optimization under the
marketable-limit fill model (docs/SIM_FILL_MODEL_DESIGN.md step 4).

Same 13-param search space as vwap_optuna_run.py plus a tunable entry
headroom (14 params), evaluated with:
  - multi-candidate mode (arm 10 / max 3) — live parity
  - fill_model='marketable_limit' — entries resolve on the next bar,
    misses happen, exactly like live

Diagnostic that motivated this: Trial 56 sealed-2025 PnL drops from
+$2,525 (perfect fills) to +$1,188 (realistic fills), PF 5.09 -> 1.58.

Walk-forward protocol unchanged:
    TRAIN   2021-2023 | SELECT 2024 (plateau) | TEST 2025 SEALED (once)

Usage:
    python vwap_fill_optuna_run.py --start 2021-01-01 --end 2023-12-31 --trials 200 --study vwap_fill_v1
    python vwap_fill_optuna_run.py --start 2024-01-01 --end 2024-12-31 --validate-trial N --study vwap_fill_v1
"""

from __future__ import annotations
import sys
import os
import argparse
import logging
import time
from dataclasses import replace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from simulator.vwap_simulation import run_vwap_date_range_multi
from optimizer.vwap.vwap_optuna_run import (
    _build_config_from_trial, _config_from_params, OPTUNA_STORAGE,
)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s | %(levelname)-5s | %(message)s',
                    datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)

MAX_ARMED = 10
MAX_CONCURRENT = 3


def _fill_config_from_trial(trial: optuna.Trial):
    cfg = _build_config_from_trial(trial)
    return replace(
        cfg,
        fill_model='marketable_limit',
        entry_headroom_pct=trial.suggest_float('v_entry_headroom_pct', 0.05, 1.0),
    )


def _fill_config_from_params(params: dict):
    cfg = _config_from_params(params)
    return replace(
        cfg,
        fill_model='marketable_limit',
        entry_headroom_pct=params['v_entry_headroom_pct'],
    )


def create_objective(start_date: str, end_date: str, account_size: float):
    def objective(trial: optuna.Trial) -> float:
        config = _fill_config_from_trial(trial)
        result = run_vwap_date_range_multi(
            config, start_date=start_date, end_date=end_date,
            account_size=account_size,
            max_armed=MAX_ARMED, max_concurrent=MAX_CONCURRENT,
            verbose=False,
        )

        total_pnl = result.get('total_pnl', 0)
        total_trades = result.get('total_trades', 0)
        win_rate = result.get('win_rate', 0)
        max_drawdown = result.get('max_drawdown', 0)
        profit_factor = result.get('profit_factor', 0)

        trial.set_user_attr('total_trades', total_trades)
        trial.set_user_attr('win_rate', round(win_rate, 1))
        trial.set_user_attr('total_pnl', round(total_pnl, 2))
        trial.set_user_attr('max_drawdown', round(max_drawdown, 2))
        trial.set_user_attr('profit_factor', round(profit_factor, 2))

        if total_trades < 30:
            return -1000

        consistency_bonus = max(0, (win_rate - 50) / 50) * abs(total_pnl) * 0.1
        dd_penalty = max_drawdown * 0.3
        objective_val = total_pnl + consistency_bonus - dd_penalty

        logger.info(
            f"Trial {trial.number}: trades={total_trades} WR={win_rate:.0f}% "
            f"P&L=${total_pnl:+.2f} DD=${max_drawdown:.2f} "
            f"PF={profit_factor:.2f} -> obj={objective_val:+.2f}"
        )
        return objective_val

    return objective


def run_validation(study_name, trial_number, start_date, end_date, account_size):
    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=study_name, storage=storage)
    trial = next((t for t in study.trials if t.number == trial_number), None)
    if trial is None:
        logger.error(f"Trial {trial_number} not found in study {study_name}")
        return
    config = _fill_config_from_params(trial.params)

    print("=" * 60)
    print(f"VALIDATION (fill model ON): Trial {trial_number} from {study_name}")
    print(f"Date range: {start_date} -> {end_date}")
    print(f"Config: {config}")
    print("=" * 60)
    result = run_vwap_date_range_multi(
        config, start_date=start_date, end_date=end_date,
        account_size=account_size,
        max_armed=MAX_ARMED, max_concurrent=MAX_CONCURRENT,
        verbose=True, print_dates=True,
    )
    print()
    print(f"Trades: {result['total_trades']}  WR: {result['win_rate']:.1f}%  "
          f"P&L: ${result['total_pnl']:+,.2f}  PF: {result['profit_factor']:.2f}  "
          f"DD: ${result['max_drawdown']:.2f}")


def main():
    parser = argparse.ArgumentParser(description='VWAP Reclaim optimizer (fill model ON)')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--trials', type=int, default=200)
    parser.add_argument('--study', default='vwap_fill_v1')
    parser.add_argument('--account-size', type=float, default=5000.0)
    parser.add_argument('--validate-trial', type=int, default=None)
    args = parser.parse_args()

    if args.validate_trial is not None:
        run_validation(args.study, args.validate_trial,
                       args.start, args.end, args.account_size)
        return

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.create_study(
        study_name=args.study, storage=storage, direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10),
        load_if_exists=True,
    )
    existing = len(study.trials)
    logger.info(f"Study '{args.study}': {existing} existing trials, running {args.trials} more")
    logger.info(f"Date range: {args.start} -> {args.end} | multi arm={MAX_ARMED}/max={MAX_CONCURRENT} | fill=marketable_limit")

    objective = create_objective(args.start, args.end, args.account_size)
    t0 = time.time()
    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)
    elapsed = time.time() - t0

    print()
    print("=" * 60)
    print(f"STUDY COMPLETE: {args.study}")
    print(f"Total trials: {len(study.trials)} | Best #{study.best_trial.number} obj={study.best_value:+.2f}")
    print(f"Elapsed: {elapsed/60:.1f} min")
    for k, v in sorted(study.best_params.items()):
        print(f"  {k}: {v}")
    print("REMINDER: plateau-select on 2024, then ONE sealed 2025 run.")


if __name__ == '__main__':
    main()
