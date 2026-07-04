"""
micro_pullback_cluster_diverse.py — find the top-N DIVERSE configs from mp_v1.

Problem: the top trials by objective are often near-duplicates (TPE clusters its
samples around the optimum), so validating "top 10 by objective" just retests the
same config 10 times. We want 10 STRUCTURALLY different configs to learn which
distinct regions of the parameter space generalize.

Method:
  1. Pull the top `--pool` trials by objective (default 50).
  2. Min-max normalize each of the 14 params to [0,1] using the study's search
     bounds (so no single wide-range param dominates the distance).
  3. Greedy max-min (farthest-point) selection: always keep #1 (best objective),
     then repeatedly add the candidate whose nearest-already-picked distance is
     largest. This spreads picks across the space instead of hugging the optimum.
  4. Print the 10 picks with their params + train metrics, and emit ready-to-run
     validation commands for 2024 + 2025.

Usage:
    python micro_pullback_cluster_diverse.py --study mp_v1 --pool 50 --pick 10
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

# Search bounds from _build_config_from_trial — used to normalize distances.
PARAM_BOUNDS = {
    'm_min_gap_pct': (5.0, 30.0),
    'm_min_relative_volume': (2.0, 15.0),
    'm_max_price': (10.0, 30.0),
    'm_max_float': (5_000_000, 50_000_000),
    'm_lookback_bars': (6, 12),
    'm_max_pullback_bars': (1, 4),
    'm_max_pullback_retrace': (2.0, 15.0),
    'm_pullback_vol_ratio': (0.5, 1.0),
    'm_resume_vol_mult': (1.0, 3.0),
    'm_profit_target_pct': (2.0, 12.0),
    'm_max_hold_bars': (5, 40),
    'm_trailing_stop_pct': (0.0, 3.0),
    'm_risk_pct': (1.0, 5.0),
    'm_max_position_pct': (10.0, 50.0),
}
PARAM_KEYS = list(PARAM_BOUNDS.keys())


def _normalize(params: dict) -> list[float]:
    out = []
    for k in PARAM_KEYS:
        lo, hi = PARAM_BOUNDS[k]
        v = params.get(k, lo)
        out.append((v - lo) / (hi - lo) if hi > lo else 0.0)
    return out


def _dist(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--study', default='mp_v1')
    ap.add_argument('--pool', type=int, default=50, help='top-N by objective to cluster')
    ap.add_argument('--pick', type=int, default=10, help='how many diverse configs to select')
    args = ap.parse_args()

    storage = optuna.storages.RDBStorage(url=OPTUNA_STORAGE)
    study = optuna.load_study(study_name=args.study, storage=storage)

    # Completed trials with a real objective, sorted best-first.
    completed = [t for t in study.trials
                 if t.value is not None and t.state == optuna.trial.TrialState.COMPLETE]
    completed.sort(key=lambda t: t.value, reverse=True)
    pool = completed[:args.pool]
    print(f"Study {args.study}: {len(completed)} completed trials, pooling top {len(pool)}")

    vecs = {t.number: _normalize(t.params) for t in pool}

    # Greedy max-min: seed with best objective, then farthest-point each step.
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
    print("VALIDATION COMMANDS (2024 select + 2025 seal)")
    print("=" * 78)
    nums = [str(t.number) for t in picked]
    print(f"# diverse trial numbers: {', '.join(nums)}")
    for t in picked:
        print(f"python micro_pullback_optuna_run.py --start 2024-01-01 --end 2024-12-31 "
              f"--validate-trial {t.number} --study {args.study}")
        print(f"python micro_pullback_optuna_run.py --start 2025-01-01 --end 2025-06-18 "
              f"--validate-trial {t.number} --study {args.study}")


if __name__ == '__main__':
    main()
