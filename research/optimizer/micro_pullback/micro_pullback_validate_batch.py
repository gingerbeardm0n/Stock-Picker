"""
micro_pullback_validate_batch.py — validate N trials across 2024 + 2025 in one pass.

Loads each trial's params from the study, runs the sim on the select (2024) and
seal (2025) windows, and prints a single comparison table sorted by 2025 P&L so
the most robust DIVERSE config is obvious at a glance.

Usage:
    python micro_pullback_validate_batch.py --study mp_v1 --trials 159,108,199,167,118,198,127,168,140,182
"""

from __future__ import annotations
import sys
import os
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from micro_pullback_optuna_run import _config_from_params  # reuse exact reconstruction
from simulator.micro_pullback_simulation import run_micro_pullback_date_range

OPTUNA_STORAGE = os.getenv(
    'OPTUNA_STORAGE',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)

WINDOWS = {
    '2024': ('2024-01-01', '2024-12-31'),
    '2025': ('2025-01-01', '2025-06-18'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', default='mp_v1')
    ap.add_argument('--trials', required=True, help='comma-separated trial numbers')
    ap.add_argument('--account-size', type=float, default=5000.0)
    args = ap.parse_args()

    trial_nums = [int(x) for x in args.trials.split(',')]

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=args.study, storage=storage)
    by_num = {t.number: t for t in study.trials}

    rows = []
    for tn in trial_nums:
        t = by_num.get(tn)
        if t is None:
            print(f"  Trial {tn} not found, skipping")
            continue
        config = _config_from_params(t.params)
        rec = {'trial': tn, 'train_obj': t.value}
        for label, (start, end) in WINDOWS.items():
            r = run_micro_pullback_date_range(
                config, start_date=start, end_date=end,
                account_size=args.account_size, verbose=False,
            )
            rec[f'{label}_trades'] = r['total_trades']
            rec[f'{label}_wr'] = r['win_rate']
            rec[f'{label}_pnl'] = r['total_pnl']
            rec[f'{label}_dd'] = r['max_drawdown']
            rec[f'{label}_pf'] = r['profit_factor']
        rows.append(rec)
        print(f"  done trial {tn}: "
              f"2024 ${rec['2024_pnl']:,.0f} ({rec['2024_wr']:.0f}%) | "
              f"2025 ${rec['2025_pnl']:,.0f} ({rec['2025_wr']:.0f}%)")

    # Sort by 2025 (seal) P&L — true out-of-sample robustness.
    rows.sort(key=lambda r: r['2025_pnl'], reverse=True)

    print()
    print("=" * 104)
    print(f"{'Trial':>6} | {'TrainObj':>9} | "
          f"{'24 Trd':>6} {'24 WR':>6} {'24 P&L':>9} {'24 PF':>6} | "
          f"{'25 Trd':>6} {'25 WR':>6} {'25 P&L':>9} {'25 PF':>6}")
    print("-" * 104)
    for r in rows:
        print(f"{r['trial']:>6} | {r['train_obj']:>+9.0f} | "
              f"{r['2024_trades']:>6} {r['2024_wr']:>5.0f}% ${r['2024_pnl']:>8,.0f} {r['2024_pf']:>6.2f} | "
              f"{r['2025_trades']:>6} {r['2025_wr']:>5.0f}% ${r['2025_pnl']:>8,.0f} {r['2025_pf']:>6.2f}")
    print("=" * 104)
    print("Sorted by 2025 (seal) P&L — top row = most robust out-of-sample.")


if __name__ == '__main__':
    main()
