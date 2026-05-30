"""
golden_baseline.py — regression oracle for the sim→orchestrator migration.

The migration (docs/LIVE_SIM_PARITY_SPEC.md) moves the per-minute decision logic out of
simulation_engine into trading/orchestrator. Each step MUST keep sim output byte-identical.
This harness captures the current sim's exact per-trade output on a fixed day-set, then
re-checks it after each step.

Usage (run from research/):
    python optimizer/golden_baseline.py --capture     # write the reference (do ONCE, pre-migration)
    python optimizer/golden_baseline.py --check       # re-run + diff vs reference; exit 1 if changed

Deterministic: fixed dates, default RunConfig, fixed gapper universe, news cache off.
The compared payload is the per-trade list (symbol/prices/shares/pnl/reason/hold) + the
aggregate metrics — i.e. everything a behavior change would perturb.
"""

from __future__ import annotations
import sys
import os
import csv
import json
import argparse

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))            # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

from optimizer.run_config import RunConfig
from optimizer.simulate_one import run_date_range

# Representative 2025 H1 days (spread across the quarter; varied temperature/outcomes).
# Fixed so the regression is reproducible. Within gapper-universe coverage.
GOLDEN_DAYS = [
    '2025-01-06',
    '2025-01-23',
    '2025-02-12',
    '2025-03-05',
    '2025-03-20',
]

_UNIVERSE_CSV = os.path.join(os.path.dirname(__file__), 'data', 'gapper_universe.csv')
_REF_PATH = os.path.join(os.path.dirname(__file__), 'data', 'golden_baseline.json')

_METRIC_KEYS = ('total_trades', 'winners', 'losers', 'win_rate', 'profit_factor',
                'total_pnl', 'avg_daily_pnl', 'max_drawdown', 'days_traded', 'objective')


def load_universe(path: str) -> dict[str, list[str]]:
    universe: dict[str, list[str]] = {}
    with open(path, newline='') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2 and row[0].strip() and row[1].strip():
                universe.setdefault(row[0].strip(), []).append(row[1].strip())
    return universe


def _round_trade(t: dict) -> dict:
    """Normalize a trade row for stable diffing (round floats)."""
    return {
        'date': t.get('date'),
        'symbol': t.get('symbol'),
        'pattern': t.get('pattern'),
        'entry_price': round(float(t.get('entry_price', 0)), 4),
        'exit_price': round(float(t.get('exit_price', 0)), 4),
        'shares': t.get('shares'),
        'pnl': round(float(t.get('pnl', 0)), 2),
        'exit_reason': t.get('exit_reason'),
        'hold_minutes': t.get('hold_minutes'),
    }


def run_golden() -> dict:
    cfg = RunConfig.defaults()
    universe = load_universe(_UNIVERSE_CSV)
    r = run_date_range(
        cfg,
        GOLDEN_DAYS[0], GOLDEN_DAYS[-1],   # metadata labels only (dates= overrides range)
        symbol_universe=universe,
        dates=GOLDEN_DAYS,
    )
    payload = {
        'days': GOLDEN_DAYS,
        'metrics': {k: r.get(k) for k in _METRIC_KEYS},
        'trades': [_round_trade(t) for t in r.get('trades', [])],
    }
    return payload


def main():
    ap = argparse.ArgumentParser(description='Golden-day regression oracle for the migration')
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--capture', action='store_true', help='write the reference baseline (pre-migration)')
    g.add_argument('--check', action='store_true', help='re-run and diff vs the reference; exit 1 if changed')
    args = ap.parse_args()

    payload = run_golden()

    if args.capture:
        with open(_REF_PATH, 'w') as f:
            json.dump(payload, f, indent=2)
        print(f"CAPTURED golden baseline -> {_REF_PATH}")
        print(f"  {payload['metrics']['total_trades']} trades over {len(GOLDEN_DAYS)} days; "
              f"total_pnl={payload['metrics']['total_pnl']}, objective={payload['metrics']['objective']}")
        return

    # --check
    if not os.path.exists(_REF_PATH):
        print(f"NO REFERENCE at {_REF_PATH} — run --capture first.")
        sys.exit(2)
    with open(_REF_PATH) as f:
        ref = json.load(f)

    if payload == ref:
        print(f"PASS: golden days byte-identical ({payload['metrics']['total_trades']} trades, "
              f"total_pnl={payload['metrics']['total_pnl']}).")
        return

    print("FAIL: golden-day output DIFFERS from reference.")
    # Metric-level diff
    for k in _METRIC_KEYS:
        if ref['metrics'].get(k) != payload['metrics'].get(k):
            print(f"  metric {k}: ref={ref['metrics'].get(k)} -> now={payload['metrics'].get(k)}")
    # Trade-count + first divergent trade
    rt, pt = ref['trades'], payload['trades']
    if len(rt) != len(pt):
        print(f"  trade count: ref={len(rt)} -> now={len(pt)}")
    for i, (a, b) in enumerate(zip(rt, pt)):
        if a != b:
            print(f"  first differing trade #{i}:\n    ref={a}\n    now={b}")
            break
    sys.exit(1)


if __name__ == '__main__':
    main()
