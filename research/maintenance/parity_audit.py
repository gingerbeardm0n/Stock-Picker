"""
parity_audit.py — Automated sim/live/optimizer parity checker.

Tier 1 (structural): fast source-code checks (~5 sec). Run as pre-commit hook.
Tier 2 (behavioral): reserved for heavier execution-parity tests (future).

Outputs:
  - Human-readable report to stdout
  - JSON results to research/maintenance/parity_results.json
  - Compares against parity_baseline.json to detect regressions

Exit codes:
  0 = no regressions (same or fewer failures than baseline)
  1 = regression detected (new failure IDs not in baseline)

Usage:
    python research/maintenance/parity_audit.py                 # check
    python research/maintenance/parity_audit.py --update-baseline  # accept current as new baseline
"""

from __future__ import annotations
import sys, os, re, json
from pathlib import Path

# Ensure production/ and research/ importable
sys.path.insert(0, os.path.abspath('production'))
sys.path.insert(0, os.path.abspath('research'))

SCRIPT_DIR = Path(__file__).parent
BASELINE_PATH = SCRIPT_DIR / 'parity_baseline.json'
RESULTS_PATH  = SCRIPT_DIR / 'parity_results.json'

# Collect all check results
_results: list[dict] = []


def check(check_id: str, name: str, passed: bool, detail: str = "", category: str = ""):
    """Record a single check result."""
    _results.append({
        'id': check_id,
        'name': name,
        'passed': passed,
        'detail': detail if not passed else '',
        'category': category,
    })


# ── Audit functions ──────────────────────────────────────────────────────────

def audit_shared_entry_path():
    cat = "1_shared_pipeline"
    with open('production/simulator/simulation_engine.py') as f:
        sim_code = f.read()
    check("sim_creates_orchestrator", "Sim creates Orchestrator",
          "self.orch = Orchestrator(" in sim_code, category=cat)
    check("sim_calls_on_minute", "Sim calls orch.on_minute()",
          "self.orch.on_minute(" in sim_code, category=cat)

    with open('production/trading/live_scanner.py') as f:
        live_code = f.read()
    has_orch = "Orchestrator(" in live_code or "self.orch" in live_code
    check("live_uses_orchestrator", "Live uses Orchestrator",
          has_orch,
          "live_scanner.py should use Orchestrator for trading decisions", cat)


def audit_discovery_parity():
    cat = "2_discovery_parity"
    with open('production/trading/orchestrator.py') as f:
        orch_code = f.read()
    check("orch_uses_qualifies_momentum", "Orchestrator uses qualifies_momentum()",
          "qualifies_momentum(" in orch_code, category=cat)

    with open('production/trading/live_scanner.py') as f:
        live_code = f.read()
    check("live_uses_qualifies_momentum", "Live intraday scan uses qualifies_momentum()",
          "qualifies_momentum(" in live_code,
          "live_scanner.py intraday scan uses ScannerConfig instead of qualifies_momentum()", cat)

    divergent_patterns = [
        ("live_no_scfg_price",     r'scfg\.min_price.*scfg\.max_price',
         "Live uses scfg.min_price/max_price (should use MomentumScanConfig)"),
        ("live_no_scfg_gain",      r'scfg\.min_premarket_gain',
         "Live uses scfg.min_premarket_gain (should use MomentumScanConfig.min_intraday_gain)"),
        ("live_no_enable_price",   r'scfg\.enable_price_range',
         "Live gates on ScannerConfig.enable_price_range (redundant)"),
        ("live_no_enable_gain",    r'scfg\.enable_premarket_gain',
         "Live gates on ScannerConfig.enable_premarket_gain (redundant)"),
        ("live_no_enable_relvol",  r'scfg\.enable_relative_volume',
         "Live gates on ScannerConfig.enable_relative_volume (redundant)"),
    ]
    for cid, pattern, msg in divergent_patterns:
        matches = re.findall(pattern, live_code)
        check(cid, f"No divergent filter: {pattern[:40]}",
              len(matches) == 0,
              f"{len(matches)} occurrences — {msg}", cat)


def audit_config_consistency():
    cat = "3_config_consistency"
    from trading.models import ScannerConfig, MomentumScanConfig
    scfg = ScannerConfig()
    mcfg = MomentumScanConfig()

    check("min_price_consistent", "min_price consistent",
          scfg.min_price == mcfg.min_price,
          f"Scanner={scfg.min_price} vs Momentum={mcfg.min_price}", cat)
    check("max_price_consistent", "max_price consistent",
          scfg.max_price == mcfg.max_price,
          f"Scanner={scfg.max_price} vs Momentum={mcfg.max_price}", cat)
    check("max_float_consistent", "max_float consistent",
          scfg.max_float == mcfg.max_float,
          f"Scanner={scfg.max_float} vs Momentum={mcfg.max_float}", cat)
    check("min_relvol_consistent", "min_relative_volume consistent",
          scfg.min_relative_volume == mcfg.min_relative_volume,
          f"Scanner={scfg.min_relative_volume} vs Momentum={mcfg.min_relative_volume}", cat)
    check("scan_end_hour_consistent", "scan_end_hour consistent",
          scfg.scan_end_hour == mcfg.scan_end_hour,
          f"Scanner={scfg.scan_end_hour} vs Momentum={mcfg.scan_end_hour}", cat)
    check("gain_threshold_unified", "Gain threshold unified",
          scfg.min_premarket_gain == mcfg.min_intraday_gain,
          f"Scanner.min_premarket_gain={scfg.min_premarket_gain}% vs Momentum.min_intraday_gain={mcfg.min_intraday_gain}%", cat)


def audit_dead_gates():
    cat = "4_dead_gates"
    with open('production/trading/entry_engine.py') as f:
        ee_code = f.read()
    for field, label in [
        ('cfg.enable_price_range',      'price_range'),
        ('cfg.enable_premarket_gain',   'premarket_gain'),
        ('cfg.enable_relative_volume',  'relative_volume'),
        ('cfg.enable_float_filter',     'float_filter'),
    ]:
        check(f"no_dead_gate_{label}", f"No dead gate: {field}",
              field not in ee_code,
              f"{field} re-gated in _check_5_pillars (qualifies_momentum handles this)", cat)


def audit_hardcoded_constants():
    cat = "5_hardcoded"
    with open('production/simulator/simulation_engine.py') as f:
        se_code = f.read()
    match = re.search(r'MIN_GAIN\s*=\s*([\d.]+)', se_code)
    if match:
        min_gain = float(match.group(1))
        check("min_gain_not_too_narrow", "MIN_GAIN <= MomentumScanConfig floor",
              min_gain <= 5.0,
              f"MIN_GAIN={min_gain} but floor=5.0 — hot_symbols superset too narrow", cat)

    with open('production/trading/entry_engine.py') as f:
        ee_code = f.read()
    has_hardcoded_end = re.search(r'^TRADING_END_HOUR\s*=\s*\d+', ee_code, re.MULTILINE)
    check("no_hardcoded_trading_end", "No hardcoded TRADING_END_HOUR",
          has_hardcoded_end is None,
          "TRADING_END_HOUR still hardcoded — should read from ScannerConfig.scan_end_hour", cat)


def audit_optuna_search_space():
    cat = "6_optuna_hygiene"
    with open('research/optimizer/optuna_run.py') as f:
        optuna_code = f.read()
    dead_params = [
        'a_enable_price_range',
        'a_enable_premarket_gain',
        'a_enable_relative_volume',
        'a_enable_float_filter',
    ]
    for param in dead_params:
        found = f"'{param}'" in optuna_code or f'"{param}"' in optuna_code
        check(f"no_dead_optuna_{param}", f"No dead Optuna param: {param}",
              not found,
              f"Optuna tunes {param} but _check_5_pillars no longer uses it", cat)


# ── Main ─────────────────────────────────────────────────────────────────────

def run_audit(update_baseline: bool = False) -> int:
    """Run all checks, compare vs baseline, return exit code."""
    audit_shared_entry_path()
    audit_discovery_parity()
    audit_config_consistency()
    audit_dead_gates()
    audit_hardcoded_constants()
    audit_optuna_search_space()

    # Build results
    failures = [r for r in _results if not r['passed']]
    failure_ids = sorted(set(r['id'] for r in failures))
    passes = [r for r in _results if r['passed']]

    results_json = {
        'total_checks': len(_results),
        'passed': len(passes),
        'failed': len(failures),
        'failure_ids': failure_ids,
    }

    # Write results
    RESULTS_PATH.write_text(json.dumps(results_json, indent=2))

    # Print human-readable
    print("=" * 60)
    print("PARITY AUDIT — sim / live / optimizer divergence check")
    print("=" * 60)

    current_cat = None
    for r in _results:
        if r['category'] != current_cat:
            current_cat = r['category']
            print(f"\n=== {current_cat} ===")
        status = "PASS" if r['passed'] else "FAIL"
        icon = "  " if r['passed'] else "!!"
        print(f"  [{status}] {icon} {r['name']}")
        if r['detail']:
            print(f"         {r['detail']}")

    # Compare vs baseline
    baseline_ids = set()
    if BASELINE_PATH.exists():
        baseline = json.loads(BASELINE_PATH.read_text())
        baseline_ids = set(baseline.get('failure_ids', []))

    current_ids = set(failure_ids)
    new_failures = current_ids - baseline_ids
    fixed_failures = baseline_ids - current_ids

    print(f"\n{'=' * 60}")
    print(f"Total: {len(_results)} checks, {len(passes)} passed, {len(failures)} failed")

    if fixed_failures:
        print(f"\n  FIXED since baseline ({len(fixed_failures)}):")
        for fid in sorted(fixed_failures):
            print(f"    - {fid}")

    if new_failures:
        print(f"\n  NEW REGRESSIONS ({len(new_failures)}):")
        for fid in sorted(new_failures):
            detail = next((r['detail'] for r in failures if r['id'] == fid), '')
            print(f"    !! {fid}: {detail}")

    if not new_failures:
        if not failures:
            print("\nRESULT: ALL CHECKS PASS")
        else:
            print(f"\nRESULT: {len(failures)} known failures (no regressions)")
        exit_code = 0
    else:
        print(f"\nRESULT: {len(new_failures)} NEW REGRESSIONS — review above")
        exit_code = 1

    # Update baseline if requested
    if update_baseline:
        BASELINE_PATH.write_text(json.dumps(results_json, indent=2))
        print(f"\nBaseline updated: {BASELINE_PATH} ({len(failure_ids)} known failures)")

    return exit_code


if __name__ == '__main__':
    update = '--update-baseline' in sys.argv
    sys.exit(run_audit(update_baseline=update))
