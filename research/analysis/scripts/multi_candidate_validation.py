"""
Multi-candidate scalp validation — single-entry baseline vs live-parity
multi mode (MAX_ARMED=10, MAX_CONCURRENT=3), Trial 173 config UNCHANGED.

Walk-forward split per anti-overfit playbook:
  train  2021-2023, select 2024, sealed 2025 (report last, no tuning).

Usage:  python research/analysis/scripts/multi_candidate_validation.py
Writes: research/analysis/outputs/multi_candidate_validation.txt (+ prints)
"""
import sys, os, json, logging, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))
logging.basicConfig(level=logging.ERROR)

from simulator.scalp_simulation import run_scalp_date_range, run_scalp_date_range_multi
from trading.live_scalp_runner import TRIAL_173_CONFIG as cfg

PERIODS = [
    ('train 2021', '2021-01-01', '2021-12-31'),
    ('train 2022', '2022-01-01', '2022-12-31'),
    ('train 2023', '2023-01-01', '2023-12-31'),
    ('select 2024', '2024-01-01', '2024-12-31'),
    ('SEALED 2025', '2025-01-01', '2025-12-31'),
]

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs',
                                   'multi_candidate_validation.txt'))
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def fmt(r):
    return (f"trades={r['total_trades']:4d} wr={r['win_rate']:5.1f}% "
            f"pnl=${r['total_pnl']:+9.2f} avg/day=${r['avg_daily_pnl']:+7.2f} "
            f"pf={r['profit_factor']:5.2f} maxDD=${r['max_drawdown']:8.2f}")


def main():
    lines = ["Multi-candidate scalp validation — Trial 173 config, "
             "single vs multi (arm 10 / max 3)", "=" * 100]
    for name, start, end in PERIODS:
        t0 = time.time()
        single = run_scalp_date_range(cfg, start, end, verbose=False)
        multi = run_scalp_date_range_multi(cfg, start, end, verbose=False)
        el = time.time() - t0
        lines.append(f"\n{name}  ({start} → {end})   [{el:.0f}s]")
        lines.append(f"  single: {fmt(single)}")
        lines.append(f"  multi : {fmt(multi)}")
        # flush progressively so partial results survive interruption
        with open(OUT, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
        print(f"{name} done ({el:.0f}s)")
    print("\n".join(lines))
    print(f"\nWritten: {OUT}")


if __name__ == '__main__':
    main()
