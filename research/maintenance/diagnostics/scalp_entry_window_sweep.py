"""
scalp_entry_window_sweep.py — does the Opening Bell Scalp edge survive a longer
entry window (the full 9:30-11:00 morning) or is it an open-only play?

Sweeps max_entry_bars (= how many minutes past 9:30 we still allow a FIRST entry)
on the trial-173 scalp config across 2025, then buckets the widest-window trades
by entry time to show edge decay. Descriptive analysis only (2025 = most
data-complete; NOT a selection/optimization decision).
"""
import sys, os
from dataclasses import replace

sys.path.insert(0, os.path.abspath('production'))

from trading.live_scalp_runner import TRIAL_173_CONFIG
from simulator.scalp_simulation import run_scalp_date_range

START, END = '2025-01-01', '2025-12-31'
ACCT = 5000.0

print(f"Scalp entry-window sweep  {START}..{END}  (trial 173, max_hold_bars="
      f"{TRIAL_173_CONFIG.max_hold_bars})")
print("=" * 72)

for meb in [4, 10, 20, 30, 60, 90]:
    cfg = replace(TRIAL_173_CONFIG, max_entry_bars=meb)
    r = run_scalp_date_range(cfg, START, END, account_size=ACCT, verbose=False)
    print(f"max_entry_bars={meb:3d} (entry by 9:{30+meb if meb<30 else ''}{'' if meb<30 else f'{(30+meb)//60+9}:{(30+meb)%60:02d}'}) "
          f"| trades={r['total_trades']:3d} WR={r['win_rate']:5.1f}% "
          f"PnL=${r['total_pnl']:+9.2f} PF={r['profit_factor']:>5.2f} DD=${r['max_drawdown']:.2f}")

print("\nEdge decay by entry time (widest window, max_entry_bars=90):")
print("-" * 72)
cfg = replace(TRIAL_173_CONFIG, max_entry_bars=90)
r = run_scalp_date_range(cfg, START, END, account_size=ACCT, verbose=False)
buckets = {'09:30-09:40': [], '09:40-10:00': [], '10:00-10:30': [], '10:30-11:00': []}
for t in r['trades']:
    et = t.entry_time
    m = et.hour * 60 + et.minute
    if m < 580:
        b = '09:30-09:40'
    elif m < 600:
        b = '09:40-10:00'
    elif m < 630:
        b = '10:00-10:30'
    else:
        b = '10:30-11:00'
    buckets[b].append(t.pnl)

for b, pnls in buckets.items():
    if pnls:
        wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
        avg = sum(pnls) / len(pnls)
        print(f"  {b}: {len(pnls):3d} trades  WR={wr:5.1f}%  total=${sum(pnls):+9.2f}  avg=${avg:+7.2f}")
    else:
        print(f"  {b}:   0 trades")
