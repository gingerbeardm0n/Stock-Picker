"""
oracle_objective.py — Optuna objective for the market-temperature oracle test.

Identical search space to optuna_run.py (it reuses _build_config_from_trial), but
instead of a contiguous start->end range it evaluates each trial over an EXPLICIT
list of trading days — the days that carry one ground-truth temperature label.

One objective serves all four studies (hot / neutral / cold / universal); only the
`days` list and the run_id prefix differ. Trades are written to results.db under
run_id `oracle_<regime>_<NNNNN>` so the held-out evaluator can reload the best
config by trial number without cross-regime collisions.
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))            # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import time
import traceback as _traceback

import optuna

from optimizer.optuna_run import _build_config_from_trial
from optimizer.simulate_one import run_date_range
from optimizer.results_db import write_run


def make_oracle_objective(
    regime: str,
    train_days: list[str],
    results_conn,
    mode: str = 'full',
    debug: bool = False,
    cache_data: bool = False,
    cache_dir: str | None = None,
    locked_params: dict | None = None,
    heartbeat=None,
):
    """Return an Optuna objective closure that scores a trial over `train_days`.

    Args mirror optuna_run._make_objective, minus start/end (replaced by the
    explicit `train_days` list) and plus `regime` for run_id tagging.
    """
    if not train_days:
        raise ValueError(f"oracle objective for regime '{regime}' got an empty train_days list")

    # Metadata labels only (run_date_range ignores these when `dates` is set).
    start_label = train_days[0]
    end_label   = train_days[-1]

    def objective(trial: optuna.Trial) -> float:
        cfg = _build_config_from_trial(
            trial, mode=mode, locked_params=locked_params,
        )

        _days_done = [0]

        def _day_tick(date: str):
            _days_done[0] += 1
            if heartbeat is not None:
                heartbeat.update(trial.number, date, _days_done[0])

        t0 = time.time()
        try:
            result = run_date_range(
                cfg,
                start_label,
                end_label,
                verbose=False,
                debug=debug,
                cache_data=cache_data,
                cache_dir=cache_dir,
                on_day_complete=_day_tick,
                print_dates=(trial.number == 0),
                early_abort_days=20,
                dates=train_days,            # <-- scattered day-subset
            )
        except Exception as e:
            print(f"\n  [{regime}] Trial {trial.number} ERROR after "
                  f"{time.time() - t0:.1f}s: {e}", flush=True)
            _traceback.print_exc()
            return -999.0

        if result['total_trades'] == 0:
            raise optuna.TrialPruned()

        trades = result.pop('trades')
        run_id = f"oracle_{regime}_{trial.number:05d}"
        write_run(results_conn, run_id, start_label, end_label,
                  result, cfg.to_flat_dict(), trades)

        return result['objective']

    return objective
