"""
scalp_optuna_run.py — Bayesian optimization for Opening Bell Scalp strategy.

Only 14 parameters in the search space (vs 126 in the main optimizer).
Uses TPE sampler + MedianPruner, same Optuna infrastructure.

Results storage:
    - PostgreSQL via optuna.storages.RDBStorage (same server as main optimizer)
    - Study name: scalp_<name>

Usage:
    python scalp_optuna_run.py --start 2025-01-01 --end 2025-06-30 --trials 200
    python scalp_optuna_run.py --start 2025-01-01 --end 2025-06-30 --trials 200 --study scalp_v1

Walk-forward validation:
    python scalp_optuna_run.py --start 2025-07-01 --end 2025-12-31 --validate-trial 42 --study scalp_v1
"""

from __future__ import annotations
import sys
import os
import argparse
import logging
import time
import threading

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))  # production/

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna")
    sys.exit(1)

from trading.scalp_models import ScalpConfig
from simulator.scalp_simulation import run_scalp_date_range

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

# PostgreSQL storage (same server as main optimizer)
OPTUNA_STORAGE = os.getenv(
    'OPTUNA_STORAGE',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)


def _build_scalp_config_from_trial(trial: optuna.Trial) -> ScalpConfig:
    """Map Optuna trial to ScalpConfig. 14 parameters."""
    return ScalpConfig(
        # Screening (4)
        min_gap_pct=trial.suggest_float('s_min_gap_pct', 5.0, 30.0),
        min_relative_volume=trial.suggest_float('s_min_relative_volume', 2.0, 15.0),
        max_float=trial.suggest_int('s_max_float', 5_000_000, 50_000_000, step=5_000_000),
        max_price=trial.suggest_float('s_max_price', 10.0, 30.0),

        # News (1)
        require_news=True,  # Always require news — core edge per Ross Cameron corpus

        # Entry (3)
        entry_mode=trial.suggest_categorical('s_entry_mode',
                                             ['pm_high_break', 'market_open', 'first_green']),
        max_entry_bars=trial.suggest_int('s_max_entry_bars', 1, 5),
        min_pm_high_break_pct=trial.suggest_float('s_min_pm_high_break_pct', 0.0, 2.0),

        # Exit (4)
        profit_target_pct=trial.suggest_float('s_profit_target_pct', 1.0, 10.0),
        stop_loss_pct=trial.suggest_float('s_stop_loss_pct', 0.5, 5.0),
        max_hold_bars=trial.suggest_int('s_max_hold_bars', 1, 10),
        trailing_stop_pct=trial.suggest_float('s_trailing_stop_pct', 1.0, 5.0),

        # Sizing (2)
        risk_pct=trial.suggest_float('s_risk_pct', 1.0, 5.0),
        max_position_pct=trial.suggest_float('s_max_position_pct', 10.0, 50.0),
    )


def create_objective(start_date: str, end_date: str, account_size: float):
    """Create the Optuna objective function."""

    def objective(trial: optuna.Trial) -> float:
        config = _build_scalp_config_from_trial(trial)

        result = run_scalp_date_range(
            config,
            start_date=start_date,
            end_date=end_date,
            account_size=account_size,
            verbose=False,
        )

        total_pnl = result.get('total_pnl', 0)
        total_trades = result.get('total_trades', 0)
        win_rate = result.get('win_rate', 0)
        max_drawdown = result.get('max_drawdown', 0)
        profit_factor = result.get('profit_factor', 0)

        # Log trial summary
        trial.set_user_attr('total_trades', total_trades)
        trial.set_user_attr('win_rate', round(win_rate, 1))
        trial.set_user_attr('total_pnl', round(total_pnl, 2))
        trial.set_user_attr('max_drawdown', round(max_drawdown, 2))
        trial.set_user_attr('profit_factor', round(profit_factor, 2))

        # Objective: total P&L with a small consistency bonus.
        # Penalize configs that trade very rarely (< 10 trades).
        # This is deliberately simpler than the main optimizer's objective.
        if total_trades < 3:
            return -1000  # too few trades to evaluate

        # Consistency bonus: reward win rate above 50%
        consistency_bonus = max(0, (win_rate - 50) / 50) * abs(total_pnl) * 0.1

        # Drawdown penalty
        dd_penalty = max_drawdown * 0.3

        objective_val = total_pnl + consistency_bonus - dd_penalty

        logger.info(
            f"Trial {trial.number}: "
            f"trades={total_trades} WR={win_rate:.0f}% "
            f"P&L=${total_pnl:+.2f} DD=${max_drawdown:.2f} "
            f"PF={profit_factor:.2f} -> obj={objective_val:+.2f}"
        )

        return objective_val

    return objective


def run_validation(study_name: str, trial_number: int,
                   start_date: str, end_date: str, account_size: float):
    """Run a specific trial's config on a validation date range."""

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=study_name, storage=storage)

    trial = None
    for t in study.trials:
        if t.number == trial_number:
            trial = t
            break

    if trial is None:
        logger.error(f"Trial {trial_number} not found in study {study_name}")
        return

    # Reconstruct config from trial params
    config = ScalpConfig(
        min_gap_pct=trial.params['s_min_gap_pct'],
        min_relative_volume=trial.params['s_min_relative_volume'],
        max_float=trial.params['s_max_float'],
        max_price=trial.params['s_max_price'],
        require_news=True,  # Always require news
        entry_mode=trial.params['s_entry_mode'],
        max_entry_bars=trial.params['s_max_entry_bars'],
        min_pm_high_break_pct=trial.params['s_min_pm_high_break_pct'],
        profit_target_pct=trial.params['s_profit_target_pct'],
        stop_loss_pct=trial.params['s_stop_loss_pct'],
        max_hold_bars=trial.params['s_max_hold_bars'],
        trailing_stop_pct=trial.params['s_trailing_stop_pct'],
        risk_pct=trial.params['s_risk_pct'],
        max_position_pct=trial.params['s_max_position_pct'],
    )

    print("=" * 60)
    print(f"VALIDATION: Trial {trial_number} from {study_name}")
    print(f"Date range: {start_date} -> {end_date}")
    print(f"Config: {config}")
    print("=" * 60)

    result = run_scalp_date_range(
        config,
        start_date=start_date,
        end_date=end_date,
        account_size=account_size,
        verbose=True,
        print_dates=True,
    )

    print()
    print("=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    print(f"Days traded:    {result['days_traded']}")
    print(f"Total trades:   {result['total_trades']}")
    print(f"Win rate:       {result['win_rate']:.1f}%")
    print(f"Total P&L:      ${result['total_pnl']:,.2f}")
    print(f"Avg daily P&L:  ${result['avg_daily_pnl']:,.2f}")
    print(f"Max drawdown:   ${result['max_drawdown']:,.2f}")
    print(f"Profit factor:  {result['profit_factor']:.2f}")


def main():
    parser = argparse.ArgumentParser(description='Opening Bell Scalp optimizer')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--trials', type=int, default=200, help='Number of trials')
    parser.add_argument('--study', default='scalp_v1', help='Study name')
    parser.add_argument('--account-size', type=float, default=5000.0)
    parser.add_argument('--validate-trial', type=int, default=None,
                        help='Run validation for a specific trial number')

    args = parser.parse_args()

    if args.validate_trial is not None:
        run_validation(args.study, args.validate_trial,
                       args.start, args.end, args.account_size)
        return

    # Create or load study
    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.create_study(
        study_name=args.study,
        storage=storage,
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10),
        load_if_exists=True,
    )

    existing = len(study.trials)
    logger.info(f"Study '{args.study}': {existing} existing trials, running {args.trials} more")
    logger.info(f"Date range: {args.start} -> {args.end}")
    logger.info(f"Search space: 14 parameters")

    objective = create_objective(args.start, args.end, args.account_size)

    t0 = time.time()
    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)
    elapsed = time.time() - t0

    # Summary
    print()
    print("=" * 60)
    print(f"STUDY COMPLETE: {args.study}")
    print("=" * 60)
    print(f"Total trials:   {len(study.trials)}")
    print(f"Best trial:     #{study.best_trial.number}")
    print(f"Best objective: {study.best_value:+.2f}")
    print(f"Elapsed:        {elapsed/60:.1f} min")
    print()
    print("Best params:")
    for k, v in sorted(study.best_params.items()):
        print(f"  {k}: {v}")
    print()

    # Print user attrs from best trial
    best = study.best_trial
    print(f"Best trial details:")
    print(f"  Trades:       {best.user_attrs.get('total_trades', '?')}")
    print(f"  Win rate:     {best.user_attrs.get('win_rate', '?')}%")
    print(f"  P&L:          ${best.user_attrs.get('total_pnl', '?')}")
    print(f"  Max drawdown: ${best.user_attrs.get('max_drawdown', '?')}")
    print(f"  Profit factor: {best.user_attrs.get('profit_factor', '?')}")


if __name__ == '__main__':
    main()
