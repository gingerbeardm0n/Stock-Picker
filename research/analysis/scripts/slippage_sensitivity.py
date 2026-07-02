"""
Slippage sensitivity — does the scalp edge survive market-fallback fills?

Live evidence (2026-07-02): limit-at-signal-close entries suffer adverse
selection — 12/15 attempts unfilled (price ran = the winners), 2 fills both
came on falling bars (= losers). The realistic alternative is a marketable
entry paying up to ~2% slippage (MP/VWAP runners' existing market-fallback).

This post-processes the multi-mode sim's trade list with entry slippage
applied: entry' = entry * (1 + slip), pnl' = (exit - entry') * shares.
First-order estimate (stop/target levels not re-simulated), good enough to
see whether the edge dies.

Usage:  python research/analysis/scripts/slippage_sensitivity.py
"""
import sys, os, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))
logging.basicConfig(level=logging.ERROR)

from simulator.scalp_simulation import run_scalp_date_range_multi
from trading.live_scalp_runner import TRIAL_173_CONFIG as cfg

SLIPS = [0.0, 0.0025, 0.005, 0.01, 0.02]
PERIODS = [('select 2024', '2024-01-01', '2024-12-31'),
           ('SEALED 2025', '2025-01-01', '2025-12-31')]

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs',
                                   'slippage_sensitivity.txt'))
os.makedirs(os.path.dirname(OUT), exist_ok=True)

lines = ["Scalp multi (arm 10 / max 3) — entry slippage sensitivity, Trial 173",
         "pnl' = (exit - entry*(1+slip)) * shares   [stops not re-simulated]",
         "=" * 78]

for name, start, end in PERIODS:
    r = run_scalp_date_range_multi(cfg, start, end, verbose=False)
    trades = r['trades']
    lines.append(f"\n{name}: {len(trades)} trades")
    for slip in SLIPS:
        pnl = sum((t.exit_price - t.entry_price * (1 + slip)) * t.shares for t in trades)
        wins = sum(1 for t in trades if (t.exit_price - t.entry_price * (1 + slip)) > 0)
        wr = wins / len(trades) * 100 if trades else 0
        lines.append(f"  slip {slip * 100:4.2f}%  pnl=${pnl:+9.2f}  wr={wr:5.1f}%")
    print(f"{name} done")

with open(OUT, 'w', encoding='utf-8') as f:
    f.write("\n".join(lines) + "\n")
for line in lines:
    print(line)
