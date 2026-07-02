"""
Fill-model diagnostic (SIM_FILL_MODEL_DESIGN.md step 2) — do the production
configs survive marketable-limit fills?

Runs all 3 strategies (Trial 173 / 56 / 167) in multi mode (arm 10 / max 3)
on 2024 select + 2025 sealed, perfect vs marketable_limit (+0.25% headroom).

Usage:  python research/analysis/scripts/fill_model_diagnostic.py
Writes: research/analysis/outputs/fill_model_diagnostic.txt
"""
import sys, os, logging, time
from dataclasses import replace
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))
logging.basicConfig(level=logging.ERROR)

from simulator.scalp_simulation import run_scalp_date_range_multi
from simulator.vwap_simulation import run_vwap_date_range_multi
from simulator.micro_pullback_simulation import run_micro_pullback_date_range_multi
from trading.live_scalp_runner import TRIAL_173_CONFIG as scalp_cfg
from trading.live_vwap_runner import TRIAL_56_CONFIG as vwap_cfg
from trading.live_micro_pullback_runner import TRIAL_167_CONFIG as mp_cfg

STRATS = [
    ('SCALP (Trial 173)', run_scalp_date_range_multi, scalp_cfg),
    ('VWAP (Trial 56)', run_vwap_date_range_multi, vwap_cfg),
    ('MICRO-PULLBACK (Trial 167)', run_micro_pullback_date_range_multi, mp_cfg),
]
PERIODS = [('select 2024', '2024-01-01', '2024-12-31'),
           ('SEALED 2025', '2025-01-01', '2025-12-31')]

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs',
                                   'fill_model_diagnostic.txt'))
os.makedirs(os.path.dirname(OUT), exist_ok=True)


def fmt(r):
    return (f"trades={r['total_trades']:4d} wr={r['win_rate']:5.1f}% "
            f"pnl=${r['total_pnl']:+9.2f} avg/day=${r['avg_daily_pnl']:+7.2f} "
            f"pf={r['profit_factor']:5.2f} maxDD=${r['max_drawdown']:8.2f}")


def main():
    lines = ["Fill-model diagnostic — multi (arm 10 / max 3), production configs",
             "perfect vs marketable_limit (+0.25% headroom, next-bar resolution)",
             "=" * 100]
    for sname, fn, cfg in STRATS:
        ml_cfg = replace(cfg, fill_model='marketable_limit')
        lines.append(f"\n>>> {sname}")
        for pname, start, end in PERIODS:
            t0 = time.time()
            perfect = fn(cfg, start, end, verbose=False)
            ml = fn(ml_cfg, start, end, verbose=False)
            el = time.time() - t0
            lines.append(f"\n{pname}  [{el:.0f}s]")
            lines.append(f"  perfect : {fmt(perfect)}")
            lines.append(f"  mkt-lim : {fmt(ml)}")
            miss_delta = perfect['total_trades'] - ml['total_trades']
            lines.append(f"  (missed fills: {miss_delta:+d} trades vs perfect)")
            with open(OUT, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
            print(f"{sname} {pname} done ({el:.0f}s)")
    for line in lines:
        print(line)
    print(f"\nWritten: {OUT}")


if __name__ == '__main__':
    main()
