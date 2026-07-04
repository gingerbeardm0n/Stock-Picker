"""
vwap_cluster_diverse.py — find top-N DIVERSE configs from vwap_v1.

Same method as micro_pullback_cluster_diverse.py:
  1. Pull top --pool trials by objective.
  2. Min-max normalize 13 params to [0,1] (categorical entry_mode → 0/1).
  3. Greedy max-min farthest-point selection.
  4. Print picks + emit ready-to-run validation commands.

Usage:
    python vwap_cluster_diverse.py --study vwap_v1 --pool 50 --pick 10
"""

from __future__ import annotations
import sys
import os
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

OPTUNA_STORAGE = os.getenv(
    'OPTUNA_STORAGE',
    'postgresql://postgres:changeme123@localhost:5432/stockdata'
)

PARAM_BOUNDS = {
    'v_min_gap_pct':          (5.0, 30.0),
    'v_min_relative_volume':  (1.5, 10.0),
    'v_max_price':            (10.0, 30.0),
    'v_lookback_bars':        (3, 10),
    'v_min_bars_below':       (1, 4),
    'v_reclaim_vol_mult':     (1.0, 2.5),
    'v_entry_mode':           (0, 1),   # reclaim_close=0, reclaim_high_break=1
    'v_stop_vwap_offset':     (0.01, 0.10),
    'v_profit_target_pct':    (2.0, 15.0),
    'v_max_hold_bars':        (5, 60),
    'v_trailing_stop_pct':    (0.0, 5.0),
    'v_risk_pct':             (1.0, 5.0),
    'v_max_position_pct':     (10.0, 50.0),
}
PARAM_KEYS = list(PARAM_BOUNDS.keys())

ENTRY_MODE_MAP = {'reclaim_close': 0, 'reclaim_high_break': 1}


def _normalize(params: dict) -> list[float]:
    out = []
    for k in PARAM_KEYS:
        lo, hi = PARAM_BOUNDS[k]
        raw = params.get(k, lo)
        if k == 'v_entry_mode':
            raw = ENTRY_MODE_MAP.get(raw, 0)
        out.append((raw - lo) / (hi - lo) if hi > lo else 0.0)
    return out


def _dist(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', default='vwap_v1')
    ap.add_argument('--pool', type=int, default=50)
    ap.add_argument('--pick', type=int, default=10)
    args = ap.parse_args()

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=args.study, storage=storage)

    completed = [t for t in study.trials
                 if t.value is not None and t.state == optuna.trial.TrialState.COMPLETE]
    completed.sort(key=lambda t: t.value, reverse=True)
    pool = completed[:args.pool]
    print(f"Study {args.study}: {len(completed)} completed trials, pooling top {len(pool)}")

    vecs = {t.number: _normalize(t.params) for t in pool}

    picked = [pool[0]]
    remaining = pool[1:]
    while len(picked) < args.pick and remaining:
        best_c, best_d = None, -1.0
        for c in remaining:
            nearest = min(_dist(vecs[c.number], vecs[p.number]) for p in picked)
            if nearest > best_d:
                best_d, best_c = nearest, c
        picked.append(best_c)
        remaining.remove(best_c)

    print()
    print("=" * 78)
    print(f"TOP {len(picked)} DIVERSE CONFIGS (greedy max-min over top {len(pool)})")
    print("=" * 78)
    for rank, t in enumerate(picked, 1):
        ua = t.user_attrs
        print(f"\n--- Pick {rank}: Trial #{t.number}  (obj={t.value:+.1f}) ---")
        print(f"  train: trades={ua.get('total_trades','?')} "
              f"WR={ua.get('win_rate','?')}% P&L=${ua.get('total_pnl','?')} "
              f"DD=${ua.get('max_drawdown','?')} PF={ua.get('profit_factor','?')}")
        for k in PARAM_KEYS:
            print(f"    {k}: {t.params.get(k)}")

    print()
    print("=" * 78)
    print("VALIDATION COMMANDS — run vwap_validate_batch.py with these trials")
    print("=" * 78)
    nums = ','.join(str(t.number) for t in picked)
    print(f"python vwap_validate_batch.py --study {args.study} --trials {nums}")


if __name__ == '__main__':
    main()
