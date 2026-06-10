"""
vwap_optuna_run.py — Bayesian optimization for the VWAP Reclaim strategy.

13 parameters in the search space (vs 126 in the main optimizer).
Same Optuna infrastructure as the scalp study.

Walk-forward protocol (docs/ANTI_OVERFITTING_PLAYBOOK.md):
    TRAIN   2021-01-01 -> 2023-12-31   (optimizer tunes here)
    SELECT  2024-01-01 -> 2024-12-31   (--validate-trial; pick a PLATEAU config, not the peak)
    TEST    2025 SEALED                (score the chosen config ONCE, at the very end)

Usage:
    # Train
    python vwap_optuna_run.py --start 2021-01-01 --end 2023-12-31 --trials 200 --study vwap_v1

    # Select on 2024 (run for several top-plateau trials, compare)
    python vwap_optuna_run.py --start 2024-01-01 --end 2024-12-31 --validate-trial 42 --study vwap_v1

    # Final sealed test (ONCE)
    python vwap_optuna_run.py --start 2025-01-01 --end 2025-12-31 --validate-trial 42 --study vwap_v1
"""

from __future__ import annotations
import sys
import os
import argparse
import logging
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))           # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))  # production/

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna")
    sys.exit(1)

from trading.vwap_models import VwapReclaimConfig
from simulator.vwap_simulation import run_vwap_date_range

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


def _build_config_from_trial(trial: optuna.Trial) -> VwapReclaimConfig:
    """Map Optuna trial to VwapReclaimConfig. 13 parameters."""
    return VwapReclaimConfig(
        # Screening (3) — require_news LOCKED True (no-news reclaims are tier-3)
        min_gap_pct=trial.suggest_float('v_min_gap_pct', 5.0, 30.0),
        min_relative_volume=trial.suggest_float('v_min_relative_volume', 1.5, 10.0),
        max_price=trial.suggest_float('v_max_price', 10.0, 30.0),
        require_news=True,

        # Setup (3) — corpus priors: lookback ~5, min_below >= 1, vol_mult ~1.2
        lookback_bars=trial.suggest_int('v_lookback_bars', 3, 10),
        min_bars_below=trial.suggest_int('v_min_bars_below', 1, 4),
        reclaim_vol_mult=trial.suggest_float('v_reclaim_vol_mult', 1.0, 2.5),

        # Entry (1)
        entry_mode=trial.suggest_categorical('v_entry_mode',
                                             ['reclaim_close', 'reclaim_high_break']),

        # Exit (4)
        stop_vwap_offset=trial.suggest_float('v_stop_vwap_offset', 0.01, 0.10),
        profit_target_pct=trial.suggest_float('v_profit_target_pct', 2.0, 15.0),
        max_hold_bars=trial.suggest_int('v_max_hold_bars', 5, 60),
        trailing_stop_pct=trial.suggest_float('v_trailing_stop_pct', 0.0, 5.0),

        # Sizing (2)
        risk_pct=trial.suggest_float('v_risk_pct', 1.0, 5.0),
        max_position_pct=trial.suggest_float('v_max_position_pct', 10.0, 50.0),
    )


def _config_from_params(params: dict) -> VwapReclaimConfig:
    """Reconstruct config from a stored trial's params."""
    return VwapReclaimConfig(
        min_gap_pct=params['v_min_gap_pct'],
        min_relative_volume=params['v_min_relative_volume'],
        max_price=params['v_max_price'],
        require_news=True,
        lookback_bars=params['v_lookback_bars'],
        min_bars_below=params['v_min_bars_below'],
        reclaim_vol_mult=params['v_reclaim_vol_mult'],
        entry_mode=params['v_entry_mode'],
        stop_vwap_offset=params['v_stop_vwap_offset'],
        profit_target_pct=params['v_profit_target_pct'],
        max_hold_bars=params['v_max_hold_bars'],
        trailing_stop_pct=params['v_trailing_stop_pct'],
        risk_pct=params['v_risk_pct'],
        max_position_pct=params['v_max_position_pct'],
    )


def create_objective(start_date: str, end_date: str, account_size: float):
    """Optuna objective — same shape as the scalp study's."""

    def objective(trial: optuna.Trial) -> float:
        config = _build_config_from_trial(trial)

        result = run_vwap_date_range(
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

        # Too few trades over a 3-year train window = config barely fires;
        # can't distinguish edge from luck.
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


def run_validation(study_name: str, trial_number: int,
                   start_date: str, end_date: str, account_size: float):
    """Score a stored trial's config on an out-of-sample date range."""
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
    print(f"Config: {config}")
    print("=" * 60)

    result = run_vwap_date_range(
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
    parser = argparse.ArgumentParser(description='VWAP Reclaim optimizer')
    parser.add_argument('--start', required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', required=True, help='End date (YYYY-MM-DD)')
    parser.add_argument('--trials', type=int, default=200)
    parser.add_argument('--study', default='vwap_v1')
    parser.add_argument('--account-size', type=float, default=5000.0)
    parser.add_argument('--validate-trial', type=int, default=None,
                        help='Score a stored trial on this date range instead of optimizing')
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

    existing = len(study.trials)
    logger.info(f"Study '{args.study}': {existing} existing trials, running {args.trials} more")
    logger.info(f"Date range: {args.start} -> {args.end}")
    logger.info("Search space: 13 parameters")

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
    print()
    best = study.best_trial
    print("Best trial details:")
    print(f"  Trades:        {best.user_attrs.get('total_trades', '?')}")
    print(f"  Win rate:      {best.user_attrs.get('win_rate', '?')}%")
    print(f"  P&L:           ${best.user_attrs.get('total_pnl', '?')}")
    print(f"  Max drawdown:  ${best.user_attrs.get('max_drawdown', '?')}")
    print(f"  Profit factor: {best.user_attrs.get('profit_factor', '?')}")
    print()
    print("REMINDER (anti-overfitting protocol):")
    print("  1. Do NOT trust the best trial directly.")
    print("  2. Validate top ~10 trials on 2024 (--validate-trial N --start 2024-01-01 --end 2024-12-31)")
    print("  3. Pick a PLATEAU config (good neighbors), not the lone peak.")
    print("  4. Score the chosen config ONCE on sealed 2025. That number is the truth.")


if __name__ == '__main__':
    main()
