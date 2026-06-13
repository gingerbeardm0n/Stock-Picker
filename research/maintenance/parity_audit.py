"""
parity_audit.py — Automated sim/live parity checker for active pipelines.

Checks the standalone strategy pipelines (scalp, VWAP, micro-pullback) for
sim/live divergence. Runs as a pre-commit hook (~2 sec).

Exit codes:
  0 = no regressions
  1 = regression detected

Usage:
    python research/maintenance/parity_audit.py
    python research/maintenance/parity_audit.py --update-baseline
"""

from __future__ import annotations
import sys, os, re, json
from pathlib import Path

sys.path.insert(0, os.path.abspath('production'))

SCRIPT_DIR = Path(__file__).parent
BASELINE_PATH = SCRIPT_DIR / 'parity_baseline.json'
RESULTS_PATH  = SCRIPT_DIR / 'parity_results.json'

_results: list[dict] = []


def check(check_id: str, name: str, passed: bool, detail: str = "", category: str = ""):
    _results.append({
        'id': check_id,
        'name': name,
        'passed': passed,
        'detail': detail if not passed else '',
        'category': category,
    })


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


# ── 1. Shared news gate ────────────────────────────────────────────────────

def audit_news_gate():
    cat = "1_news_gate"
    news = _read('production/backend/news_fetcher.py')
    check("news_has_catalyst_fn", "has_news_catalyst() defined",
          "def has_news_catalyst(" in news, category=cat)
    check("news_tiers_frozenset", "NEWS_CATALYST_TIERS is frozenset",
          "frozenset(" in news and "NEWS_CATALYST_TIERS" in news, category=cat)

    for label, path in [
        ("scalp_sim", "production/simulator/scalp_simulation.py"),
        ("vwap_sim", "production/simulator/vwap_simulation.py"),
        ("live_scalp", "production/trading/live_scalp_runner.py"),
        ("live_vwap", "production/trading/live_vwap_runner.py"),
    ]:
        code = _read(path)
        check(f"{label}_uses_shared_news", f"{label} imports has_news_catalyst",
              "has_news_catalyst" in code,
              f"{path} should use shared has_news_catalyst()", cat)


# ── 2. Shared engine functions ─────────────────────────────────────────────

def audit_shared_engines():
    cat = "2_shared_engines"
    for strategy, engine_path, sim_path, live_path in [
        ("scalp", "production/trading/scalp_engine.py",
         "production/simulator/scalp_simulation.py",
         "production/trading/live_scalp_runner.py"),
        ("vwap", "production/trading/vwap_engine.py",
         "production/simulator/vwap_simulation.py",
         "production/trading/live_vwap_runner.py"),
    ]:
        engine = _read(engine_path)
        check(f"{strategy}_engine_evaluate_entry", f"{strategy} engine has evaluate_entry()",
              "def evaluate_entry(" in engine, category=cat)
        check(f"{strategy}_engine_evaluate_exit", f"{strategy} engine has evaluate_exit()",
              "def evaluate_exit(" in engine, category=cat)

        sim = _read(sim_path)
        check(f"{strategy}_sim_imports_engine", f"{strategy} sim imports from engine",
              f"from trading.{strategy}_engine import" in sim,
              f"{sim_path} should import from {engine_path}", cat)

        if os.path.exists(live_path):
            live = _read(live_path)
            check(f"{strategy}_live_imports_engine", f"{strategy} live imports from engine",
                  f"from trading.{strategy}_engine import" in live
                  or f"{strategy}_engine" in live,
                  f"{live_path} should import from {engine_path}", cat)


# ── 3. Config consistency ──────────────────────────────────────────────────

def audit_config_consistency():
    cat = "3_config_consistency"
    from trading.scalp_models import ScalpConfig
    from trading.vwap_models import VwapReclaimConfig as VWAPConfig

    scalp = ScalpConfig()
    vwap = VWAPConfig()

    check("scalp_requires_news", "Scalp requires news catalyst",
          scalp.require_news is True, category=cat)
    check("vwap_requires_news", "VWAP requires news catalyst",
          vwap.require_news is True, category=cat)


# ── 4. Screening parity ───────────────────────────────────────────────────

def audit_screening_parity():
    cat = "4_screening"
    for strategy in ["scalp", "vwap"]:
        sim = _read(f"production/simulator/{strategy}_simulation.py")
        check(f"{strategy}_sim_uses_screen_candidates",
              f"{strategy} sim uses screen_candidates()",
              "screen_candidates(" in sim,
              f"{strategy}_simulation.py should use shared screen_candidates()", cat)
        check(f"{strategy}_sim_uses_rank_candidates",
              f"{strategy} sim uses rank_candidates()",
              "rank_candidates(" in sim,
              f"{strategy}_simulation.py should use shared rank_candidates()", cat)

    scalp_sim = _read("production/simulator/scalp_simulation.py")
    check("scalp_sim_has_float_filter", "Scalp sim checks max_float",
          "max_float" in scalp_sim, category=cat)

    vwap_sim = _read("production/simulator/vwap_simulation.py")
    check("vwap_sim_has_float_filter", "VWAP sim checks max_float",
          "max_float" in vwap_sim, category=cat)


# ── 5. Live runner safety ─────────────────────────────────────────────────

def audit_live_safety():
    cat = "5_live_safety"
    scalp_live = _read("production/trading/live_scalp_runner.py")
    check("scalp_max_entry_bars_documented",
          "Scalp live max_entry_bars has paper-only comment",
          "PAPER" in scalp_live.upper() or "paper" in scalp_live,
          "max_entry_bars=30 override needs PAPER-ONLY comment", cat)

    for path in [
        "production/trading/live_scalp_runner.py",
        "production/trading/live_vwap_runner.py",
    ]:
        code = _read(path)
        name = Path(path).stem
        check(f"{name}_has_dry_run", f"{name} supports dry-run mode",
              "dry_run" in code or "DRY_RUN" in code or "paper" in code.lower(),
              f"{path} should have a dry-run / paper safety gate", cat)


# ── Main ───────────────────────────────────────────────────────────────────

def run_audit(update_baseline: bool = False) -> int:
    audit_news_gate()
    audit_shared_engines()
    audit_config_consistency()
    audit_screening_parity()
    audit_live_safety()

    failures = [r for r in _results if not r['passed']]
    failure_ids = sorted(set(r['id'] for r in failures))
    passes = [r for r in _results if r['passed']]

    results_json = {
        'total_checks': len(_results),
        'passed': len(passes),
        'failed': len(failures),
        'failure_ids': failure_ids,
    }

    RESULTS_PATH.write_text(json.dumps(results_json, indent=2))

    print("=" * 60)
    print("PARITY AUDIT — sim / live / optimizer divergence check")
    print("=" * 60)

    current_cat = None
    for r in _results:
        if r['category'] != current_cat:
            current_cat = r['category']
            print(f"\n=== {current_cat} ===")
        status = "PASS" if r['passed'] else "FAIL"
        print(f"  [{status}]    {r['name']}")
        if r['detail']:
            print(f"         {r['detail']}")

    baseline_ids = set()
    if BASELINE_PATH.exists():
        baseline = json.loads(BASELINE_PATH.read_text())
        baseline_ids = set(baseline.get('failure_ids', []))

    current_ids = set(failure_ids)
    new_failures = current_ids - baseline_ids

    print(f"\n{'=' * 60}")
    print(f"Total: {len(_results)} checks, {len(passes)} passed, {len(failures)} failed")

    if not new_failures:
        if not failures:
            print("\nRESULT: ALL CHECKS PASS")
        else:
            print(f"\nRESULT: {len(failures)} known failures (no regressions)")
        exit_code = 0
    else:
        print(f"\nRESULT: {len(new_failures)} NEW REGRESSIONS — review above")
        for fid in sorted(new_failures):
            detail = next((r['detail'] for r in failures if r['id'] == fid), '')
            print(f"    !! {fid}: {detail}")
        exit_code = 1

    if update_baseline:
        BASELINE_PATH.write_text(json.dumps(results_json, indent=2))
        print(f"\nBaseline updated: {BASELINE_PATH}")

    return exit_code


if __name__ == '__main__':
    update = '--update-baseline' in sys.argv
    sys.exit(run_audit(update_baseline=update))
