"""
run_oracle_test.py — Drive the full market-temperature oracle test end to end.

Question answered: with PERFECT knowledge of each day's temperature, can
regime-specific configs beat one universal config? The gap is the CEILING any
real temperature predictor could ever capture. If the gap is ~0 (or negative),
regime-switching is not worth pursuing — stop before building a better predictor.

Pipeline (all SEQUENTIAL — never run the studies simultaneously):
    1. Load ground-truth labels + one shared chronological train/test split.
    2. Optimize 4 Optuna studies on TRAIN days, one after another:
         universal (baseline) -> hot -> neutral -> cold
    3. Held-out evaluation on TEST days:
         - oracle switching = best_hot(hot_test) + best_neutral(neutral_test)
                              + best_cold(cold_test)
         - baseline         = best_universal(universal_test)
       (universal_test == hot_test ∪ neutral_test ∪ cold_test — identical universe)
    4. Print comparison + verdict.

    python optimizer/run_oracle_test.py --trials 300
    python optimizer/run_oracle_test.py --trials 300 --skip-optimize   # eval only

PREREQUISITES:
    - Phase-1 DB backfill COMPLETE.
    - validate_market_temperature.py has been run -> hot/neutral/cold_days.csv exist.
Do NOT run while the backfill is still going (DB contention + RAM ceiling).
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))            # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

import argparse
import json
import sqlite3

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    print("ERROR: Optuna not installed. Run: pip install optuna tqdm")
    sys.exit(1)

from optimizer.run_config import RunConfig
from optimizer.simulate_one import run_date_range
from optimizer.oracle_labels import load_oracle_sets, summarize, REGIMES
from optimizer.run_oracle_study import (
    run_oracle_study, DEFAULT_OPTUNA_DB, DEFAULT_RESULTS_DB,
)

# UNIVERSAL must run first (baseline), then the three regimes.
RUN_ORDER = ('universal',) + REGIMES


def _load_best_config(
    regime: str,
    optuna_db_url: str,
    results_db_path: str,
) -> tuple[RunConfig, int, float]:
    """Reload the best trial's full config for a regime from storage.

    Returns (RunConfig, best_trial_number, best_train_objective).
    """
    study = optuna.load_study(study_name=f'oracle_{regime}', storage=optuna_db_url)
    try:
        best = study.best_trial
    except ValueError:
        raise RuntimeError(
            f"Regime '{regime}' has no completed trials in {optuna_db_url}. "
            f"Run its study first (run_oracle_study --regime {regime}) and confirm "
            f"it produced trades — a thin regime can prune every trial."
        )
    run_id = f"oracle_{regime}_{best.number:05d}"

    conn = sqlite3.connect(results_db_path)
    row = conn.execute(
        'SELECT params_json FROM runs WHERE run_id = ?', (run_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise RuntimeError(
            f"Best trial {run_id} not found in {results_db_path}. "
            f"Did the study complete and write results?"
        )
    cfg = RunConfig.from_flat_dict(json.loads(row[0]))
    return cfg, best.number, float(best.value)


def _eval_on_days(cfg: RunConfig, days: list[str], label: str) -> dict:
    """Run one config over an explicit TEST day-list. Returns metrics dict."""
    if not days:
        print(f"  [{label}] no test days — skipping")
        return {'total_pnl': 0.0, 'total_trades': 0, 'win_rate': 0.0,
                'profit_factor': 0.0, 'days_traded': 0}
    res = run_date_range(cfg, days[0], days[-1], dates=days)
    print(f"  [{label}] {len(days)} test days -> "
          f"P&L ${res['total_pnl']:,.0f} | trades {res['total_trades']} | "
          f"win {res['win_rate']:.0f}% | PF {res['profit_factor']:.2f}")
    return res


def main():
    ap = argparse.ArgumentParser(description='Run the full market-temperature oracle test')
    ap.add_argument('--trials', type=int, default=300, help='Trials per regime study')
    ap.add_argument('--test-frac', type=float, default=0.30,
                    help='Held-out fraction (chronological), shared by all regimes')
    ap.add_argument('--outputs-dir', default=None, help='Dir with hot/neutral/cold_days.csv')
    ap.add_argument('--optuna-db', default=DEFAULT_OPTUNA_DB)
    ap.add_argument('--db', default=DEFAULT_RESULTS_DB)
    ap.add_argument('--mode', default='full', choices=['full', 'gates-only', 'single-indicator'])
    ap.add_argument('--cache-data', action='store_true')
    ap.add_argument('--cache-dir', default='data/cache')
    ap.add_argument('--skip-optimize', action='store_true',
                    help='Skip the 4 studies; just reload best configs and run the held-out eval')
    args = ap.parse_args()

    # ── 1. Shared split ───────────────────────────────────────────────────────
    sets = load_oracle_sets(args.outputs_dir, args.test_frac)
    print("Oracle day-label split (shared by all regimes):")
    print(summarize(sets))
    print()

    # ── 2. Optimize 4 studies sequentially ────────────────────────────────────
    if not args.skip_optimize:
        for regime in RUN_ORDER:
            print(f"\n########## OPTIMIZE: {regime.upper()} ##########")
            run_oracle_study(
                regime=regime,
                n_trials=args.trials,
                test_frac=args.test_frac,
                outputs_dir=args.outputs_dir,
                optuna_db_url=args.optuna_db,
                results_db_path=args.db,
                mode=args.mode,
                cache_data=args.cache_data,
                cache_dir=args.cache_dir if args.cache_data else None,
                oracle_sets=sets,   # reuse identical split — no re-load drift
            )
    else:
        print("--skip-optimize: reusing existing studies, running held-out eval only.\n")

    # ── 3. Held-out evaluation on TEST days ───────────────────────────────────
    print(f"\n{'='*60}")
    print("HELD-OUT EVALUATION (test days, never seen in training)")
    print(f"{'='*60}")

    # Baseline: universal config on the full test universe.
    uni_cfg, uni_n, uni_train_obj = _load_best_config('universal', args.optuna_db, args.db)
    print(f"\nUniversal baseline (best trial #{uni_n}, train obj ${uni_train_obj:,.0f}):")
    uni_test = _eval_on_days(uni_cfg, sets.universal_test, 'universal')
    baseline_pnl = uni_test['total_pnl']

    # Oracle switching: each regime config on its own test days.
    print("\nOracle switching (regime config on its own test days):")
    oracle_pnl = 0.0
    per_regime = {}
    for regime in REGIMES:
        cfg, n, train_obj = _load_best_config(regime, args.optuna_db, args.db)
        res = _eval_on_days(cfg, sets.test[regime], regime)
        per_regime[regime] = res
        oracle_pnl += res['total_pnl']

    # ── 4. Verdict ────────────────────────────────────────────────────────────
    gap = oracle_pnl - baseline_pnl
    gap_pct = (gap / abs(baseline_pnl) * 100.0) if baseline_pnl else float('nan')

    print(f"\n{'='*60}")
    print("RESULT")
    print(f"{'='*60}")
    print(f"  Universal baseline P&L : ${baseline_pnl:,.0f}")
    print(f"  Oracle switching  P&L : ${oracle_pnl:,.0f}")
    for r in REGIMES:
        print(f"      {r:<8} : ${per_regime[r]['total_pnl']:,.0f} "
              f"({per_regime[r]['total_trades']} trades)")
    print(f"  ---------------------------------------------")
    print(f"  Ceiling (oracle - baseline): ${gap:,.0f}  ({gap_pct:+.1f}%)")
    print()
    if gap <= 0:
        print("  VERDICT: Regime-switching does NOT beat the universal config even with")
        print("           PERFECT labels. A real predictor cannot help. STOP — do not")
        print("           invest in a better temperature predictor.")
    else:
        print(f"  VERDICT: Perfect labels add ${gap:,.0f} ({gap_pct:+.1f}%). That is the")
        print("           CEILING. A real (imperfect) predictor captures only a fraction.")
        print("           Worth pursuing only if this ceiling is large enough to justify")
        print("           the predictor work.")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
