"""
validate_findings.py — run ONE backtest over a fixed range and print its metrics as JSON.

Used to validate the corpus-audit findings (docs/CORPUS_THRESHOLD_AUDIT.md): run a baseline,
then apply a finding (config override here, or a code edit elsewhere), rerun the SAME range,
and compare. A finding is kept only if metrics are neutral-or-better on the `consistency`
objective (and not worse on green_day_rate / payoff / max_drawdown).

Scanner mode (symbol_universe=None) = dynamic per-day discovery from the DB, so no universe
file is needed. Run from the research/ directory (matches the optimizer cwd convention):

    python optimizer/validate_findings.py --start 2025-01-01 --end 2025-06-30 --label baseline
    python optimizer/validate_findings.py --start 2025-01-01 --end 2025-06-30 --label F2_relvol3 --rel-vol 3.0

For code-edit findings (F11 un-MACD-gate vwap, E1 per-temp time_decay): edit the engine, then
run this with the same --start/--end/--label and diff the JSON against the baseline run.
"""

from __future__ import annotations
import sys
import os
import csv
import json
import argparse

_DEFAULT_UNIVERSE = os.path.join(os.path.dirname(__file__), 'data', 'gapper_universe.csv')


def load_universe(path: str) -> dict[str, list[str]]:
    """Load a date-specific symbol universe from a CSV whose first two columns are
    (date 'YYYY-MM-DD', symbol). Extra columns ignored. Returns {date_str: [symbols]}.
    Matches optuna_run.py's date-specific loader convention."""
    universe: dict[str, list[str]] = {}
    with open(path, newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)  # skip header row
        for row in reader:
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                continue
            universe.setdefault(row[0].strip(), []).append(row[1].strip())
    return universe

# Mirror simulate_one.py's path setup so `optimizer.*` and engine imports resolve.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))            # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

from optimizer.run_config import RunConfig
from optimizer.simulate_one import run_date_range

_KEYS = ('total_trades', 'winners', 'losers', 'win_rate', 'profit_factor',
         'total_pnl', 'avg_daily_pnl', 'max_drawdown', 'days_traded', 'objective')


def main():
    ap = argparse.ArgumentParser(description='Run one backtest, print metrics JSON (findings validation)')
    ap.add_argument('--start', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='YYYY-MM-DD')
    ap.add_argument('--label', default='run', help='tag for this run in the output JSON')
    # Optional config overrides for config-only findings (no code edit needed):
    ap.add_argument('--rel-vol', type=float, default=None, help='F2: override ScannerConfig.min_relative_volume')
    ap.add_argument('--min-gain', type=float, default=None, help='override ScannerConfig.min_premarket_gain')
    ap.add_argument('--universe', default=_DEFAULT_UNIVERSE,
                    help='date-specific universe CSV (date,symbol,...). "none" = scanner mode (slow).')
    args = ap.parse_args()

    cfg = RunConfig.defaults()
    overrides = {}
    if args.rel_vol is not None:
        cfg.scanner.min_relative_volume = args.rel_vol
        overrides['min_relative_volume'] = args.rel_vol
    if args.min_gain is not None:
        cfg.scanner.min_premarket_gain = args.min_gain
        overrides['min_premarket_gain'] = args.min_gain

    universe = None
    if args.universe and args.universe.lower() != 'none':
        universe = load_universe(args.universe)

    r = run_date_range(cfg, args.start, args.end, symbol_universe=universe)

    out = {'label': args.label, 'start': args.start, 'end': args.end, 'overrides': overrides}
    out.update({k: r.get(k) for k in _KEYS})
    # green_day_rate isn't in the returned dict; derive from per-day if available is not exposed,
    # so report what we have. objective already bakes in green-day + payoff + dd.
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
