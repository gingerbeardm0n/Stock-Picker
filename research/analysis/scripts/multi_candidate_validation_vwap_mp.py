"""
Multi-candidate VWAP + Micro-Pullback validation -- single-entry baseline vs
live-parity multi mode (MAX_ARMED=10, MAX_CONCURRENT=3), production configs.

Walk-forward split per anti-overfit playbook:
  train  2021-2023, select 2024, sealed 2025 (report last, no tuning).

Usage:  python research/analysis/scripts/multi_candidate_validation_vwap_mp.py
Writes: research/analysis/outputs/multi_candidate_validation_vwap_mp.txt
"""
import sys, os, logging, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))
logging.basicConfig(level=logging.ERROR)

from simulator.vwap_simulation import run_vwap_date_range, run_vwap_date_range_multi
from simulator.micro_pullback_simulation import (
    run_micro_pullback_date_range, run_micro_pullback_date_range_multi,
)
from trading.live_vwap_runner import TRIAL_56_CONFIG as vwap_cfg
from trading.live_micro_pullback_runner import TRIAL_167_CONFIG as mp_cfg

PERIODS = [
    ('train 2021', '2021-01-01', '2021-12-31'),
    ('train 2022', '2022-01-01', '2022-12-31'),
    ('train 2023', '2023-01-01', '2023-12-31'),
    ('select 2024', '2024-01-01', '2024-12-31'),
    ('SEALED 2025', '2025-01-01', '2025-12-31'),
]

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs',
                                   'multi_candidate_validation_vwap_mp.txt'))
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def fmt(r):
    return (f"trades={r['total_trades']:4d} wr={r['win_rate']:5.1f}% "
            f"pnl=${r['total_pnl']:+9.2f} avg/day=${r['avg_daily_pnl']:+7.2f} "
            f"pf={r['profit_factor']:5.2f} maxDD=${r['max_drawdown']:8.2f}")


def main():
    lines = ["Multi-candidate validation -- VWAP (Trial 56) + Micro-Pullback (Trial 167)",
             "single vs multi (arm 10 / max 3)", "=" * 100]

    # ── VWAP ──────────────────────────────────────────────────────────────
    lines.append("\n>>> VWAP RECLAIM (Trial 56 config)")
    lines.append("-" * 80)
    for name, start, end in PERIODS:
        t0 = time.time()
        single = run_vwap_date_range(vwap_cfg, start, end, verbose=False)
        multi = run_vwap_date_range_multi(vwap_cfg, start, end, verbose=False)
        el = time.time() - t0
        lines.append(f"\n{name}  ({start} -> {end})   [{el:.0f}s]")
        lines.append(f"  single: {fmt(single)}")
        lines.append(f"  multi : {fmt(multi)}")
        with open(OUT, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
        print(f"VWAP {name} done ({el:.0f}s)")

    # ── Micro-Pullback ────────────────────────────────────────────────────
    lines.append("\n\n>>> MICRO-PULLBACK (Trial 167 config)")
    lines.append("-" * 80)
    for name, start, end in PERIODS:
        t0 = time.time()
        single = run_micro_pullback_date_range(mp_cfg, start, end, verbose=False)
        multi = run_micro_pullback_date_range_multi(mp_cfg, start, end, verbose=False)
        el = time.time() - t0
        lines.append(f"\n{name}  ({start} -> {end})   [{el:.0f}s]")
        lines.append(f"  single: {fmt(single)}")
        lines.append(f"  multi : {fmt(multi)}")
        with open(OUT, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
        print(f"MP {name} done ({el:.0f}s)")

    # Print to stdout (safe for Windows cp1252)
    for line in lines:
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode('ascii', 'replace').decode())
    print(f"\nWritten: {OUT}")


if __name__ == '__main__':
    main()
