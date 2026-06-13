"""Batch-validate selected scalp_v1 trials on an out-of-sample date range.

Usage:
    python validate_batch.py 2024-01-01 2024-12-31
    python validate_batch.py 2025-01-01 2025-12-31
"""
import sys, os, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.ERROR)
logging.disable(logging.WARNING)

from simulator.scalp_simulation import run_scalp_date_range
from trading.scalp_models import ScalpConfig

OPTUNA_STORAGE = 'postgresql://postgres:changeme123@localhost:5432/stockdata'

# Trials to validate:
# 173 = champion (train winner, walk-forward validated)
# 139, 136 = similar obj, lower gap% (8.6%) — more trades, same WR profile
# 65, 91, 79, 103 = ~5-6% gap cluster — higher WR (81-84%), untested OOS
TRIALS = [173, 139, 136, 65, 91, 79, 103]

START, END = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:  # optional: comma-separated trial list override
    TRIALS = [int(x) for x in sys.argv[3].split(',')]

study = optuna.load_study(study_name='scalp_v1', storage=OPTUNA_STORAGE)
by_num = {t.number: t for t in study.trials}


def config_from_params(params: dict) -> ScalpConfig:
    return ScalpConfig(
        min_gap_pct=params['s_min_gap_pct'],
        min_relative_volume=params['s_min_relative_volume'],
        max_float=params['s_max_float'],
        max_price=params['s_max_price'],
        require_news=True,
        entry_mode=params['s_entry_mode'],
        max_entry_bars=params['s_max_entry_bars'],
        min_pm_high_break_pct=params['s_min_pm_high_break_pct'],
        profit_target_pct=params['s_profit_target_pct'],
        stop_loss_pct=params['s_stop_loss_pct'],
        max_hold_bars=params['s_max_hold_bars'],
        trailing_stop_pct=params['s_trailing_stop_pct'],
        risk_pct=params['s_risk_pct'],
        max_position_pct=params['s_max_position_pct'],
    )


print(f"\nScalp OOS validation: {START} -> {END}")
print(f"{'trial':>6} {'gap%':>6} {'rv':>5} {'train_obj':>10} | {'trades':>7} {'WR':>6} {'pnl':>10} {'avg/day':>9} {'maxDD':>8} {'PF':>5}")
print('-' * 85)

for num in TRIALS:
    t = by_num[num]
    p = t.params
    cfg = config_from_params(p)
    r = run_scalp_date_range(cfg, START, END, account_size=5000.0, verbose=False)
    print(
        f"{num:>6} {p['s_min_gap_pct']:>6.2f} {p['s_min_relative_volume']:>5.2f} "
        f"{t.value:>+10.1f} | "
        f"{r['total_trades']:>7} {r['win_rate']:>5.1f}% "
        f"{r['total_pnl']:>+10.2f} {r['avg_daily_pnl']:>+9.2f} "
        f"{r['max_drawdown']:>8.2f} {r['profit_factor']:>5.2f}",
        flush=True,
    )
