"""
micro_pullback_optuna_run.py — Bayesian optimization for the Micro-Pullback strategy (#3).

14 parameters in the search space (vs 126 in the main optimizer). TPE sampler +
MedianPruner, same Optuna infrastructure as the scalp / VWAP studies. Walk-forward
discipline (docs/ANTI_OVERFITTING_PLAYBOOK.md): tune on TRAIN, select on a held-out
year, seal the final year once.

Usage:
    # train
    python micro_pullback_optuna_run.py --start 2021-01-01 --end 2023-12-31 --trials 200 --study mp_v1
    # select (score a trial on the unseen 2024 year)
    python micro_pullback_optuna_run.py --start 2024-01-01 --end 2024-12-31 --validate-trial 42 --study mp_v1
    # seal (ONE shot on 2025, after selection is locked)
    python micro_pullback_optuna_run.py --start 2025-01-01 --end 2025-12-31 --validate-trial 42 --study mp_v1
"""

from __future__ import annotations
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))          # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))  # production/

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna")
    sys.exit(1)

from trading.micro_pullback_models import MicroPullbackConfig
from simulator.micro_pullback_simulation import run_micro_pullback_date_range

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-5s | %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

OPTUNA_STORAGE = os.getenv(
    'OPTUNA_STORAGE',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)


def _build_config_from_trial(trial: optuna.Trial) -> MicroPullbackConfig:
    """Map Optuna trial to MicroPullbackConfig. 14 parameters."""
    return MicroPullbackConfig(
        # Screening (4 + news lock)
        min_gap_pct=trial.suggest_float('m_min_gap_pct', 5.0, 30.0),
        min_relative_volume=trial.suggest_float('m_min_relative_volume', 2.0, 15.0),
        max_price=trial.suggest_float('m_max_price', 10.0, 30.0),
        max_float=trial.suggest_int('m_max_float', 5_000_000, 50_000_000, step=5_000_000),
        require_news=True,  # core edge per corpus

        # Setup (5)
        lookback_bars=trial.suggest_int('m_lookback_bars', 6, 12),
        max_pullback_bars=trial.suggest_int('m_max_pullback_bars', 1, 4),
        max_pullback_retrace=trial.suggest_float('m_max_pullback_retrace', 2.0, 15.0),
        pullback_vol_ratio=trial.suggest_float('m_pullback_vol_ratio', 0.5, 1.0),
        resume_vol_mult=trial.suggest_float('m_resume_vol_mult', 1.0, 3.0),

        # Exit (3)
        profit_target_pct=trial.suggest_float('m_profit_target_pct', 2.0, 12.0),
        max_hold_bars=trial.suggest_int('m_max_hold_bars', 5, 40),
        trailing_stop_pct=trial.suggest_float('m_trailing_stop_pct', 0.0, 3.0),

        # Sizing (2)
        risk_pct=trial.suggest_float('m_risk_pct', 1.0, 5.0),
        max_position_pct=trial.suggest_float('m_max_position_pct', 10.0, 50.0),
    )


def _config_from_params(p: dict) -> MicroPullbackConfig:
    """Reconstruct a config from a trial's stored params."""
    return MicroPullbackConfig(
        min_gap_pct=p['m_min_gap_pct'],
        min_relative_volume=p['m_min_relative_volume'],
        max_price=p['m_max_price'],
        max_float=p['m_max_float'],
        require_news=True,
        lookback_bars=p['m_lookback_bars'],
        max_pullback_bars=p['m_max_pullback_bars'],
        max_pullback_retrace=p['m_max_pullback_retrace'],
        pullback_vol_ratio=p['m_pullback_vol_ratio'],
        resume_vol_mult=p['m_resume_vol_mult'],
        profit_target_pct=p['m_profit_target_pct'],
        max_hold_bars=p['m_max_hold_bars'],
        trailing_stop_pct=p['m_trailing_stop_pct'],
        risk_pct=p['m_risk_pct'],
        max_position_pct=p['m_max_position_pct'],
    )


def create_objective(start_date: str, end_date: str, account_size: float):
    def objective(trial: optuna.Trial) -> float:
        config = _build_config_from_trial(trial)
        result = run_micro_pullback_date_range(
            config, start_date=start_date, end_date=end_date,
            account_size=account_size, verbose=False,
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

        if total_trades < 3:
            return -1000  # too few trades to evaluate

        consistency_bonus = max(0, (win_rate - 50) / 50) * abs(total_pnl) * 0.1
        dd_penalty = max_drawdown * 0.3
        objective_val = total_pnl + consistency_bonus - dd_penalty

        logger.info(
            f"Trial {trial.number}: trades={total_trades} WR={win_rate:.0f}% "
            f"P&L=${total_pnl:+.2f} DD=${max_drawdown:.2f} PF={profit_factor:.2f} "
            f"-> obj={objective_val:+.2f}"
        )
        return objective_val

    return objective


def run_validation(study_name: str, trial_number: int,
                   start_date: str, end_date: str, account_size: float):
    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=study_name, storage=storage)

    trial = next((t for t in study.trials if t.number == trial_number), None)
    if trial is None:
        logger.error(f"Trial {trial_number} not found in study {study_name}")
        return

    config = _config_from_params(trial.params)
    print("=" * 60)
    print(f"VALIDATION: Trial {trial_number} from {study_name}")
    print(f"Date range: {start_date} -> {end_date}")
    print("=" * 60)

    result = run_micro_pullback_date_range(
        config, start_date=start_date, end_date=end_date,
        account_size=account_size, verbose=True, print_dates=True,
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
    parser = argparse.ArgumentParser(description='Micro-Pullback optimizer (#3)')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--trials', type=int, default=200, help='Number of trials')
    parser.add_argument('--study', default='mp_v1', help='Study name')
    parser.add_argument('--account-size', type=float, default=5000.0)
    parser.add_argument('--validate-trial', type=int, default=None,
                        help='Run validation for a specific trial number')

    args = parser.parse_args()

    if args.validate_trial is not None:
        run_validation(args.study, args.validate_trial,
                       args.start, args.end, args.account_size)
        return

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.create_study(
        study_name=args.study,
        storage=storage,
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10),
        load_if_exists=True,
    )

    logger.info(f"Study '{args.study}': {len(study.trials)} existing trials, "
                f"running {args.trials} more")
    logger.info(f"Date range: {args.start} -> {args.end}  |  Search space: 14 parameters")

    objective = create_objective(args.start, args.end, args.account_size)
    t0 = time.time()
    study.optimize(objective, n_trials=args.trials, show_progress_bar=True)
    elapsed = time.time() - t0

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
    best = study.best_trial
    print()
    print("Best trial details:")
    print(f"  Trades:        {best.user_attrs.get('total_trades', '?')}")
    print(f"  Win rate:      {best.user_attrs.get('win_rate', '?')}%")
    print(f"  P&L:           ${best.user_attrs.get('total_pnl', '?')}")
    print(f"  Max drawdown:  ${best.user_attrs.get('max_drawdown', '?')}")
    print(f"  Profit factor: {best.user_attrs.get('profit_factor', '?')}")


if __name__ == '__main__':
    main()
