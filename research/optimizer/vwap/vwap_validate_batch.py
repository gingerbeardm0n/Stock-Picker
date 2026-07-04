"""
vwap_validate_batch.py — validate N trials across 2024 + 2025 in one pass.

Usage:
    python vwap_validate_batch.py --study vwap_v1 --trials 173,176,83,...
"""

from __future__ import annotations
import sys
import os
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

from vwap_optuna_run import _config_from_params
from simulator.vwap_simulation import run_vwap_date_range

OPTUNA_STORAGE = os.getenv(
    'OPTUNA_STORAGE',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)

WINDOWS = {
    '2016-2020': ('2016-01-01', '2020-12-31'),
    '2024': ('2024-01-01', '2024-12-31'),
    '2025': ('2025-01-01', '2025-06-18'),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', default='vwap_v1')
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
            r = run_vwap_date_range(
                config, start_date=start, end_date=end,
                account_size=args.account_size, verbose=False,
            )
            rec[f'{label}_trades'] = r['total_trades']
            rec[f'{label}_wr'] = r['win_rate']
            rec[f'{label}_pnl'] = r['total_pnl']
            rec[f'{label}_pf'] = r['profit_factor']
        rows.append(rec)
        print(f"  done trial {tn}: "
              f"2016-20 ${rec['2016-2020_pnl']:,.0f} ({rec['2016-2020_wr']:.0f}%) | "
              f"2024 ${rec['2024_pnl']:,.0f} ({rec['2024_wr']:.0f}%) | "
              f"2025 ${rec['2025_pnl']:,.0f} ({rec['2025_wr']:.0f}%)")

    rows.sort(key=lambda r: r['2025_pnl'], reverse=True)

    print()
    print("=" * 160)
    print(f"{'Trial':>6} | {'TrainObj':>9} | "
          f"{'16-20 Trd':>8} {'16-20 WR':>8} {'16-20 P&L':>11} {'16-20 PF':>8} | "
          f"{'24 Trd':>6} {'24 WR':>6} {'24 P&L':>9} {'24 PF':>6} | "
          f"{'25 Trd':>6} {'25 WR':>6} {'25 P&L':>9} {'25 PF':>6}")
    print("-" * 160)
    for r in rows:
        print(f"{r['trial']:>6} | {r['train_obj']:>+9.0f} | "
              f"{r['2016-2020_trades']:>8} {r['2016-2020_wr']:>7.0f}% ${r['2016-2020_pnl']:>10,.0f} {r['2016-2020_pf']:>7.2f} | "
              f"{r['2024_trades']:>6} {r['2024_wr']:>5.0f}% ${r['2024_pnl']:>8,.0f} {r['2024_pf']:>6.2f} | "
              f"{r['2025_trades']:>6} {r['2025_wr']:>5.0f}% ${r['2025_pnl']:>8,.0f} {r['2025_pf']:>6.2f}")
    print("=" * 160)
    print("Sorted by 2025 (seal) P&L — top row = most robust out-of-sample.")


if __name__ == '__main__':
    main()
