"""Batch-validate selected vwap_v1 trials on an out-of-sample date range."""
import sys, os, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.ERROR)
logging.disable(logging.WARNING)

from vwap_optuna_run import _config_from_params, OPTUNA_STORAGE
from simulator.vwap_simulation import run_vwap_date_range

TRIALS = [173, 176, 193, 83, 121, 123, 162, 56]
START, END = sys.argv[1], sys.argv[2]

study = optuna.load_study(study_name='vwap_v1', storage=OPTUNA_STORAGE)
by_num = {t.number: t for t in study.trials}

print(f"OOS validation {START} -> {END}")
print(f"{'trial':>5} {'train_obj':>9} | {'trades':>6} {'WR':>5} {'pnl':>9} {'avg/day':>8} {'maxDD':>8} {'PF':>5}")
for num in TRIALS:
    t = by_num[num]
    cfg = _config_from_params(t.params)
    r = run_vwap_date_range(cfg, START, END, account_size=5000.0, verbose=False)
    print(f"{num:>5} {t.value:>+9.1f} | {r['total_trades']:>6} {r['win_rate']:>4.1f}% "
          f"{r['total_pnl']:>+9.2f} {r['avg_daily_pnl']:>+8.2f} {r['max_drawdown']:>8.2f} {r['profit_factor']:>5.2f}",
          flush=True)
