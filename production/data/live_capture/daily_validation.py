#!/usr/bin/env python3
"""
daily_validation.py — Prove the historical-data pipeline matches live reality.

For a given session date D, rebuild D exactly the way our Optuna training
data was built (Alpaca backfill: daily bars for the full universe, minute
bars for movers, news, rel-vol cache), then run the SAME single-day
simulations the optimizer ran — with the configs that traded live on D —
and print the sim's trades next to what the live session actually did.

If the sim on backfilled-Alpaca data picks the same stock at the same time
with a similar result as the live session, then the historical data — and
therefore every Optuna trial tuned on it — is representative of live
reality. Differences = data-quality or selection-parity findings.

Steps (each reuses an existing script):
  1. Daily bars, full universe          research/data_backfill/backfill_daily_history.py
  2. Mover minute bars + premarket 1h   research/data_backfill/backfill_gappers_v2.py
  3. News                               production/data/backfill/backfill_news.py
  4. Rel-vol cumulative cache           research/database_analysis/build_rel_vol_cum_cache.py
  5. Single-day VWAP + scalp sims with the live configs

First run needs a catch-up window (DB stale since 2026-03-13): use
--start 2026-03-14 so prev-closes, 30d volume baselines, and the rel-vol
cache history exist. Daily runs after that: just --date (defaults to today).

Usage:
    python daily_validation.py --date 2026-06-12 --start 2026-04-25   # catch-up
    python daily_validation.py                                        # today, incremental
    python daily_validation.py --sims-only --date 2026-06-12          # skip backfills
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import argparse
import subprocess
from datetime import date, timedelta

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))

STEPS = [
    ('daily bars (universe)',
     ['python', 'research/data_backfill/backfill_daily_history.py',
      '--start', '{start}', '--end', '{end}', '--resume']),
    ('mover minute bars',
     ['python', 'research/data_backfill/backfill_gappers_v2.py',
      '--start', '{start}', '--end', '{end}', '--resume']),
    ('news',
     ['python', 'production/data/backfill/backfill_news.py',
      '--start', '{start}', '--end', '{end}']),
    ('rel-vol cache',
     ['python', 'research/database_analysis/build_rel_vol_cum_cache.py',
      '--start', '{start}', '--end', '{end}']),
]


def run_step(name: str, argv: list[str], start: str, end: str) -> bool:
    cmd = [a.format(start=start, end=end) for a in argv]
    print(f'\n=== STEP: {name} ===\n    {" ".join(cmd[1:])}')
    r = subprocess.run(cmd, cwd=REPO)
    if r.returncode != 0:
        print(f'[FAIL] {name} exited {r.returncode}')
        return False
    return True


def run_sims(day: str, account: float):
    print(f'\n{"=" * 70}\n  SINGLE-DAY SIMS ON BACKFILLED DATA — {day} (live configs)\n{"=" * 70}')

    from simulator.vwap_simulation import VwapSimulationRunner
    from trading.live_vwap_runner import TRIAL_173_CONFIG as VWAP_CFG
    print('\n--- VWAP reclaim (trial 173) ---')
    res = VwapSimulationRunner(day, config=VWAP_CFG, account_size=account, verbose=True).run()
    _print_result('vwap', res)

    from simulator.scalp_simulation import ScalpSimulationRunner
    from trading.live_scalp_runner import TRIAL_211_CONFIG as SCALP_CFG
    print('\n--- Opening-bell scalp (trial 211) ---')
    res = ScalpSimulationRunner(day, config=SCALP_CFG, account_size=account, verbose=True).run()
    _print_result('scalp', res)

    print('\nCompare each sim trade against the live session log for the same day:')
    print('  same symbol + same entry bar  -> selection & signal parity holds')
    print('  similar entry/exit prices     -> Alpaca data matches the live tape')
    print('  divergence                    -> investigate (data gap, parity bug)')


def _print_result(label: str, res: dict):
    t = res.get('trade')
    if not res.get('traded') or t is None:
        print(f'  {label}: NO TRADE (candidates={res.get("candidate_count", 0)})')
        return
    entry_t = t.entry_time.strftime('%H:%M') if hasattr(t.entry_time, 'strftime') else t.entry_time
    print(f'  {label}: {t.symbol} entry ${t.entry_price:.2f}@{entry_t} '
          f'exit ${t.exit_price:.2f} ({t.exit_type}) P&L ${t.pnl:+.2f} '
          f'shares={t.shares} bars={t.bars_held}')


def main():
    parser = argparse.ArgumentParser()
    # Default to YESTERDAY: Alpaca free tier cannot reliably serve same-day
    # minute bars (SIP clamp + unsettled data). Today's session only becomes
    # validatable historical data the next morning.
    parser.add_argument('--date', default=(date.today() - timedelta(days=1)).isoformat(),
                        help='Session date to validate (default yesterday)')
    parser.add_argument('--start', default=None,
                        help='Backfill window start (default: date - 5 days; '
                             'first/catch-up run should pass an early start)')
    parser.add_argument('--sims-only', action='store_true', help='Skip backfill steps')
    parser.add_argument('--account', type=float, default=100_000.0)
    args = parser.parse_args()

    day = args.date
    start = args.start or (date.fromisoformat(day) - timedelta(days=5)).isoformat()

    if not args.sims_only:
        for name, argv in STEPS:
            if not run_step(name, argv, start, day):
                print('Backfill step failed — fix and re-run (steps are resumable).')
                sys.exit(1)

    run_sims(day, args.account)


if __name__ == '__main__':
    main()
