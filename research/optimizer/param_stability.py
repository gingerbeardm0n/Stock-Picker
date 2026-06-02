"""
param_stability.py — Analyze which params the optimizer actually converged on.

For each param, compares distribution in top-N trials vs all trials.
Tight clustering in top-N = param matters (real signal).
Same spread as full population = noise (can be locked/removed).

Usage:
    python research/optimizer/param_stability.py --study mega_120params_v3 --top 300
"""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.abspath('research'))
sys.path.insert(0, os.path.abspath('production'))

import argparse
import numpy as np
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)


def analyze(study_name: str, storage: str, top_n: int):
    study = optuna.load_study(study_name=study_name, storage=storage)
    completed = [t for t in study.trials if t.state.name == 'COMPLETE']
    print(f"Completed trials : {len(completed)}")
    print(f"Top-N analyzed   : {top_n}  ({top_n/len(completed)*100:.1f}%)\n")

    # Sort by objective descending
    completed.sort(key=lambda t: t.value, reverse=True)
    top    = completed[:top_n]
    all_   = completed

    # Collect all param names
    all_params = set()
    for t in completed:
        all_params.update(t.params.keys())
    all_params = sorted(all_params)

    results = []
    for param in all_params:
        top_vals = [t.params[param] for t in top    if param in t.params]
        all_vals = [t.params[param] for t in all_   if param in t.params]

        if not top_vals:
            continue

        is_bool = isinstance(top_vals[0], bool)
        is_cat  = isinstance(top_vals[0], str)
        is_num  = not is_bool and not is_cat

        if is_bool or is_cat:
            # For booleans: what % of top-N is True vs overall?
            if is_bool:
                top_rate  = sum(1 for v in top_vals if v) / len(top_vals)
                all_rate  = sum(1 for v in all_vals if v) / len(all_vals)
                bias = abs(top_rate - all_rate)
                dominant = f"True={top_rate*100:.0f}%"
                signal = "STRONG" if bias > 0.20 else ("WEAK" if bias > 0.08 else "NOISE")
                results.append((signal, bias, param, dominant,
                                 f"all={all_rate*100:.0f}% vs top={top_rate*100:.0f}%"))
            else:
                from collections import Counter
                top_ctr = Counter(top_vals)
                top_mode = top_ctr.most_common(1)[0]
                all_ctr  = Counter(all_vals)
                all_rate  = all_ctr[top_mode[0]] / len(all_vals)
                top_rate  = top_mode[1] / len(top_vals)
                bias = abs(top_rate - all_rate)
                signal = "STRONG" if bias > 0.20 else ("WEAK" if bias > 0.08 else "NOISE")
                results.append((signal, bias, param, f"'{top_mode[0]}'={top_rate*100:.0f}%",
                                 f"all={all_rate*100:.0f}% vs top={top_rate*100:.0f}%"))
        else:
            # Numeric: compare std of top-N vs std of all → convergence ratio
            top_arr = np.array(top_vals, dtype=float)
            all_arr = np.array(all_vals, dtype=float)
            all_std = np.std(all_arr)
            top_std = np.std(top_arr)
            top_mean = np.mean(top_arr)
            all_mean = np.mean(all_arr)

            if all_std < 1e-9:
                continue  # constant param, skip

            # Convergence: how much tighter is top-N? 0=same spread, 1=fully converged
            convergence = 1.0 - (top_std / all_std)
            # Mean shift: did top-N converge to a different mean?
            mean_shift_pct = abs(top_mean - all_mean) / all_std if all_std > 0 else 0

            signal = "STRONG" if convergence > 0.35 else ("WEAK" if convergence > 0.15 else "NOISE")
            results.append((signal, convergence, param,
                             f"top_mean={top_mean:.3g}±{top_std:.3g}",
                             f"all_mean={all_mean:.3g}±{all_std:.3g}  shift={mean_shift_pct:.2f}σ"))

    # Sort by signal strength desc
    order = {'STRONG': 0, 'WEAK': 1, 'NOISE': 2}
    results.sort(key=lambda r: (-order.get(r[0], 3) * -1, -r[1]))
    results.sort(key=lambda r: (order[r[0]], -r[1]))

    # Print
    print(f"{'SIGNAL':<8} {'STRENGTH':>9}  {'PARAM':<45} {'TOP-N VALUE':<30} CONTEXT")
    print("-" * 130)
    for sig, strength, param, top_val, context in results:
        marker = "🔥" if sig == "STRONG" else ("~" if sig == "WEAK" else " ")
        print(f"{sig:<8} {strength:>9.3f}  {param:<45} {top_val:<30} {context}")

    # Summary
    strong = [r for r in results if r[0] == 'STRONG']
    weak   = [r for r in results if r[0] == 'WEAK']
    noise  = [r for r in results if r[0] == 'NOISE']
    print(f"\n{'='*60}")
    print(f"STRONG (optimizer converged, param matters) : {len(strong)}")
    print(f"WEAK   (mild convergence)                   : {len(weak)}")
    print(f"NOISE  (no convergence, safe to lock/drop)  : {len(noise)}")
    print(f"\nSTRONG params — lock these near top-N mean for next run:")
    for _, strength, param, top_val, _ in strong:
        print(f"  {param:<45} {top_val}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--study',   default='mega_120params_v3')
    parser.add_argument('--storage', default='sqlite:///research/optimizer/optuna.db')
    parser.add_argument('--top',     type=int, default=300)
    args = parser.parse_args()
    analyze(args.study, args.storage, args.top)
