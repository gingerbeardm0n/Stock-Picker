"""
plateau_analysis.py — Parameter plateau analysis for Optuna studies.

Identifies params where a WIDE RANGE of values all perform well (plateau)
vs params where only a narrow spike of values works (fragile/overfit).

Method:
  1. For each numeric param, bin values into N quantile buckets.
  2. Compute median objective per bucket.
  3. Measure "plateau width" = fraction of buckets within X% of the best bucket.
  4. A wide plateau means the param value doesn't matter much → safe to lock.
  5. A narrow spike means only one specific value works → possibly overfit.

For boolean params, compare median objective for True vs False trials.
If both perform similarly → param doesn't matter → lock to majority or either.

Usage:
    python research/optimizer/plateau_analysis.py [--study NAME] [--storage URL]
        [--top-n 300] [--bins 10] [--tolerance 0.10] [--lock-file FILE]
        [--output FILE]

    --top-n      Only analyze trials in top N by objective (default: all)
    --bins       Number of quantile bins per param (default: 10)
    --tolerance  Fraction of best-bucket median to consider "plateau" (default: 0.10)
    --lock-file  Skip params already locked in this JSON file
    --output     Write results JSON to this path

Created: 2026-06-02
Method: Parameter plateau concept (Harbourfronts 2026, ScienceDirect PSO paper 2024)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: optuna not installed")
    sys.exit(1)


def _load_locked_keys(lock_file: str | None) -> set[str]:
    """Load param names from a lock file (skip _ prefixed metadata keys)."""
    if not lock_file or not Path(lock_file).exists():
        return set()
    with open(lock_file) as f:
        raw = json.load(f)
    return {k for k in raw if not k.startswith('_')}


def _classify_params(trials: list) -> tuple[dict[str, list], dict[str, list]]:
    """Split param values into boolean and numeric dicts, paired with objectives."""
    bool_params: dict[str, list[tuple[bool, float]]] = {}
    num_params: dict[str, list[tuple[float, float]]] = {}

    for t in trials:
        val = t.value
        if val is None:
            continue
        for k, v in t.params.items():
            if isinstance(v, bool):
                bool_params.setdefault(k, []).append((v, val))
            elif isinstance(v, (int, float)):
                num_params.setdefault(k, []).append((float(v), val))
    return bool_params, num_params


def analyze_numeric_plateau(
    values: list[tuple[float, float]],
    n_bins: int = 10,
    tolerance: float = 0.10,
) -> dict:
    """
    Bin param values into quantile buckets, compute median objective per bucket.

    Returns dict with:
      - plateau_width: fraction of bins within tolerance of best bin (0.0-1.0)
      - best_bin_median: highest median objective across bins
      - worst_bin_median: lowest median objective across bins
      - range_pct: (best - worst) / |best| — how much objective varies across bins
      - best_bin_center: center value of the best-performing bin
      - bin_medians: list of (bin_center, median_objective) for visualization
    """
    params = np.array([v[0] for v in values])
    objectives = np.array([v[1] for v in values])

    # If all same value (already locked or degenerate), skip
    if np.std(params) < 1e-10:
        return {
            'plateau_width': 1.0,
            'best_bin_median': float(np.median(objectives)),
            'worst_bin_median': float(np.median(objectives)),
            'range_pct': 0.0,
            'best_bin_center': float(params[0]),
            'bin_medians': [],
            'verdict': 'CONSTANT',
        }

    # Create quantile bins (handles non-uniform distributions)
    try:
        bin_edges = np.quantile(params, np.linspace(0, 1, n_bins + 1))
        # Deduplicate edges (can happen with discrete params)
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < 3:
            # Too few unique values for binning
            return {
                'plateau_width': 1.0,
                'best_bin_median': float(np.median(objectives)),
                'worst_bin_median': float(np.median(objectives)),
                'range_pct': 0.0,
                'best_bin_center': float(np.median(params)),
                'bin_medians': [],
                'verdict': 'TOO_FEW_UNIQUE',
            }
    except Exception:
        return {
            'plateau_width': 0.0, 'best_bin_median': 0, 'worst_bin_median': 0,
            'range_pct': 0, 'best_bin_center': 0, 'bin_medians': [], 'verdict': 'ERROR',
        }

    actual_bins = len(bin_edges) - 1
    bin_medians = []

    for i in range(actual_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == actual_bins - 1:
            mask = (params >= lo) & (params <= hi)  # inclusive on last bin
        else:
            mask = (params >= lo) & (params < hi)
        bin_objs = objectives[mask]
        if len(bin_objs) == 0:
            continue
        center = (lo + hi) / 2.0
        bin_medians.append((float(center), float(np.median(bin_objs)), int(len(bin_objs))))

    if not bin_medians:
        return {
            'plateau_width': 0.0, 'best_bin_median': 0, 'worst_bin_median': 0,
            'range_pct': 0, 'best_bin_center': 0, 'bin_medians': [], 'verdict': 'EMPTY',
        }

    medians_only = [m[1] for m in bin_medians]
    best_median = max(medians_only)
    worst_median = min(medians_only)
    best_idx = medians_only.index(best_median)

    # Plateau width = fraction of bins within tolerance of best
    threshold = best_median * (1.0 - tolerance) if best_median > 0 else best_median * (1.0 + tolerance)
    if best_median > 0:
        in_plateau = sum(1 for m in medians_only if m >= threshold)
    else:
        # Negative objectives: "within tolerance" means not much worse
        in_plateau = sum(1 for m in medians_only if m >= threshold)

    plateau_width = in_plateau / len(medians_only)

    range_pct = abs(best_median - worst_median) / abs(best_median) if best_median != 0 else 0.0

    # Verdict
    if plateau_width >= 0.7:
        verdict = 'WIDE_PLATEAU'
    elif plateau_width >= 0.4:
        verdict = 'MODERATE_PLATEAU'
    elif plateau_width >= 0.2:
        verdict = 'NARROW'
    else:
        verdict = 'SPIKE'

    return {
        'plateau_width': round(plateau_width, 3),
        'best_bin_median': round(best_median, 1),
        'worst_bin_median': round(worst_median, 1),
        'range_pct': round(range_pct, 4),
        'best_bin_center': round(bin_medians[best_idx][0], 4),
        'bin_medians': [(round(c, 4), round(m, 1), n) for c, m, n in bin_medians],
        'verdict': verdict,
    }


def analyze_boolean_plateau(values: list[tuple[bool, float]]) -> dict:
    """Compare median objective for True vs False trials."""
    true_objs = [v[1] for v in values if v[0]]
    false_objs = [v[1] for v in values if not v[0]]

    if not true_objs or not false_objs:
        winner = True if true_objs else False
        return {
            'true_median': round(float(np.median(true_objs)), 1) if true_objs else None,
            'false_median': round(float(np.median(false_objs)), 1) if false_objs else None,
            'true_count': len(true_objs),
            'false_count': len(false_objs),
            'diff_pct': None,
            'verdict': 'ONE_SIDED',
            'better': winner,
        }

    true_med = float(np.median(true_objs))
    false_med = float(np.median(false_objs))
    best = max(true_med, false_med)
    diff_pct = abs(true_med - false_med) / abs(best) if best != 0 else 0

    if diff_pct < 0.03:
        verdict = 'PLATEAU'  # <3% difference — doesn't matter
    elif diff_pct < 0.10:
        verdict = 'MILD_PREFERENCE'
    else:
        verdict = 'STRONG_PREFERENCE'

    return {
        'true_median': round(true_med, 1),
        'false_median': round(false_med, 1),
        'true_count': len(true_objs),
        'false_count': len(false_objs),
        'diff_pct': round(diff_pct, 4),
        'verdict': verdict,
        'better': true_med >= false_med,
    }


def run_plateau_analysis(
    study_name: str = 'mega_120params_v3',
    storage: str = 'sqlite:///optuna.db',
    top_n: int | None = None,
    n_bins: int = 10,
    tolerance: float = 0.10,
    lock_file: str | None = None,
    output_file: str | None = None,
) -> dict:
    """Run full plateau analysis on an Optuna study."""
    study = optuna.load_study(study_name=study_name, storage=storage)
    completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]

    if top_n:
        completed = sorted(completed, key=lambda t: t.value, reverse=True)[:top_n]

    print(f"Analyzing {len(completed)} trials from study '{study_name}'")

    locked_keys = _load_locked_keys(lock_file)
    if locked_keys:
        print(f"Skipping {len(locked_keys)} already-locked params from {lock_file}")

    bool_params, num_params = _classify_params(completed)

    # Filter out locked params
    bool_params = {k: v for k, v in bool_params.items() if k not in locked_keys}
    num_params = {k: v for k, v in num_params.items() if k not in locked_keys}

    print(f"Params to analyze: {len(bool_params)} boolean, {len(num_params)} numeric")
    print()

    # ── Boolean analysis ──
    bool_results = {}
    print("=" * 80)
    print("BOOLEAN PARAMS — Plateau = both True and False perform similarly")
    print("=" * 80)

    bool_sorted = []
    for k, vals in sorted(bool_params.items()):
        result = analyze_boolean_plateau(vals)
        bool_results[k] = result
        bool_sorted.append((k, result))

    # Sort by diff_pct (most similar first = most plateau-like)
    bool_sorted.sort(key=lambda x: x[1].get('diff_pct') or 999)

    for k, r in bool_sorted:
        diff_str = f"{r['diff_pct']:.1%}" if r['diff_pct'] is not None else "N/A"
        better_str = "True" if r['better'] else "False"
        print(f"  {k:48s} True={r['true_median']}  False={r['false_median']}  "
              f"diff={diff_str:>6s}  {r['verdict']:20s} better={better_str}")

    # ── Numeric analysis ──
    num_results = {}
    print()
    print("=" * 80)
    print("NUMERIC PARAMS — Plateau width = fraction of bins within 10% of best")
    print("=" * 80)

    num_sorted = []
    for k, vals in sorted(num_params.items()):
        result = analyze_numeric_plateau(vals, n_bins=n_bins, tolerance=tolerance)
        num_results[k] = result
        num_sorted.append((k, result))

    # Sort by plateau_width descending (widest plateaus first)
    num_sorted.sort(key=lambda x: x[1]['plateau_width'], reverse=True)

    for k, r in num_sorted:
        if r['verdict'] in ('CONSTANT', 'TOO_FEW_UNIQUE', 'ERROR', 'EMPTY'):
            print(f"  {k:48s} {r['verdict']}")
            continue
        print(f"  {k:48s} plateau={r['plateau_width']:.0%}  "
              f"best={r['best_bin_median']:>8.0f}  worst={r['worst_bin_median']:>8.0f}  "
              f"range={r['range_pct']:.1%}  {r['verdict']:20s} peak@{r['best_bin_center']}")

    # ── Summary ──
    print()
    print("=" * 80)
    print("LOCKABLE CANDIDATES (plateau params safe to lock)")
    print("=" * 80)

    lockable_bool = [(k, r) for k, r in bool_sorted if r['verdict'] == 'PLATEAU']
    lockable_num = [(k, r) for k, r in num_sorted if r['verdict'] == 'WIDE_PLATEAU']

    if lockable_bool:
        print(f"\n  Boolean PLATEAU (<3% diff, either value works):")
        for k, r in lockable_bool:
            better_str = "True" if r['better'] else "False"
            print(f"    {k:46s} → lock to {better_str} (diff={r['diff_pct']:.1%})")

    if lockable_num:
        print(f"\n  Numeric WIDE_PLATEAU (>=70% of bins within 10% of best):")
        for k, r in lockable_num:
            print(f"    {k:46s} → lock to {r['best_bin_center']} (plateau={r['plateau_width']:.0%})")

    total_lockable = len(lockable_bool) + len(lockable_num)
    print(f"\n  Total new lockable candidates: {total_lockable}")
    print(f"  (Already locked: {len(locked_keys)}, would bring total to {len(locked_keys) + total_lockable})")

    # ── Output JSON ──
    results = {
        'study': study_name,
        'trials_analyzed': len(completed),
        'params_analyzed': len(bool_params) + len(num_params),
        'already_locked': len(locked_keys),
        'boolean': bool_results,
        'numeric': num_results,
        'lockable_boolean': {k: r for k, r in lockable_bool},
        'lockable_numeric': {k: r for k, r in lockable_num},
    }

    if output_file:
        Path(output_file).write_text(json.dumps(results, indent=2, default=str))
        print(f"\nResults written to {output_file}")

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Parameter plateau analysis for Optuna studies')
    parser.add_argument('--study', default='mega_120params_v3', help='Study name')
    parser.add_argument('--storage', default='sqlite:///optuna.db', help='Optuna storage URL')
    parser.add_argument('--top-n', type=int, default=None, help='Only analyze top N trials')
    parser.add_argument('--bins', type=int, default=10, help='Number of quantile bins (default: 10)')
    parser.add_argument('--tolerance', type=float, default=0.10,
                        help='Fraction of best bin to count as "plateau" (default: 0.10 = 10%%)')
    parser.add_argument('--lock-file', default=None, help='JSON lock file to exclude already-locked params')
    parser.add_argument('--output', default=None, help='Output JSON file path')
    args = parser.parse_args()

    run_plateau_analysis(
        study_name=args.study,
        storage=args.storage,
        top_n=args.top_n,
        n_bins=args.bins,
        tolerance=args.tolerance,
        lock_file=args.lock_file,
        output_file=args.output,
    )
