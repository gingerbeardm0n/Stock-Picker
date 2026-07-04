"""Quick validation of top 10 VWAP trials on 2016-2020 only."""

from __future__ import annotations
import sys
import os

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

trial_nums = [173, 155, 56, 166, 85, 141, 123, 103, 111, 199]

storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
study = optuna.load_study(study_name='vwap_v1', storage=storage)
by_num = {t.number: t for t in study.trials}

rows = []
for tn in trial_nums:
    t = by_num.get(tn)
    if t is None:
        print(f"  Trial {tn} not found")
        continue
    config = _config_from_params(t.params)
    r = run_vwap_date_range(
        config, start_date='2016-01-01', end_date='2020-12-31',
        account_size=5000.0, verbose=False,
    )
    rows.append({
        'trial': tn,
        'trades': r['total_trades'],
        'wr': r['win_rate'],
        'pnl': r['total_pnl'],
        'pf': r['profit_factor'],
    })
    print(f"  done trial {tn}: 2016-20 ${r['total_pnl']:,.0f} ({r['win_rate']:.0f}%) {r['profit_factor']:.2f}PF")

print()
print("=" * 70)
print(f"{'Trial':>6} | {'Trades':>6} {'WR':>6} {'P&L':>10} {'PF':>6}")
print("-" * 70)
for r in sorted(rows, key=lambda x: x['pnl'], reverse=True):
    print(f"{r['trial']:>6} | {r['trades']:>6} {r['wr']:>5.0f}% ${r['pnl']:>9,.0f} {r['pf']:>6.2f}")
print("=" * 70)
