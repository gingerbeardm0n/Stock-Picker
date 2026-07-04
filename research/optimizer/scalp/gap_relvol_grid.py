"""
Grid sweep: gap% × rel-vol interaction for Opening Bell Scalp.

Holds all other params at Trial 173 values (champion config).
Varies only min_gap_pct (5.0-12.0 by 0.5) and min_relative_volume (2.75-4.25 by 0.25).
98 combos total.

Usage:
    python gap_relvol_grid.py --start 2021-01-01 --end 2023-12-31
    python gap_relvol_grid.py --start 2025-01-01 --end 2025-06-30

Output: CSV to stdout + summary heatmap to stderr.
"""
import sys
import os
import argparse
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

import logging
logging.disable(logging.WARNING)

from trading.scalp_models import ScalpConfig
from simulator.scalp_simulation import run_scalp_date_range

TRIAL_173_BASE = dict(
    max_float=50_000_000,
    max_price=24.69,
    require_news=True,
    entry_mode='first_green',
    max_entry_bars=4,
    min_pm_high_break_pct=0.09,
    profit_target_pct=9.88,
    stop_loss_pct=4.70,
    max_hold_bars=6,
    trailing_stop_pct=0.07,
    risk_pct=2.63,
    max_position_pct=37.17,
)

GAP_VALUES = [round(5.0 + i * 0.5, 1) for i in range(15)]   # 5.0 to 12.0
RV_VALUES = [round(2.75 + i * 0.25, 2) for i in range(7)]    # 2.75 to 4.25


def main():
    parser = argparse.ArgumentParser(description='Gap% × Rel-Vol grid sweep')
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--account-size', type=float, default=5000.0)
    args = parser.parse_args()

    total = len(GAP_VALUES) * len(RV_VALUES)
    print(f"gap_pct,rel_vol,trades,win_rate,total_pnl,avg_daily_pnl,max_drawdown,profit_factor,obj")

    results = []
    done = 0
    t0 = time.time()

    for gap in GAP_VALUES:
        for rv in RV_VALUES:
            cfg = ScalpConfig(min_gap_pct=gap, min_relative_volume=rv, **TRIAL_173_BASE)
            r = run_scalp_date_range(cfg, args.start, args.end,
                                     account_size=args.account_size, verbose=False)

            trades = r['total_trades']
            wr = r['win_rate']
            pnl = r['total_pnl']
            avg = r['avg_daily_pnl']
            dd = r['max_drawdown']
            pf = r['profit_factor']

            obj = pnl + max(0, (wr - 50) / 50) * abs(pnl) * 0.1 - dd * 0.3 if trades >= 3 else -1000

            print(f"{gap},{rv},{trades},{wr:.1f},{pnl:.2f},{avg:.2f},{dd:.2f},{pf:.2f},{obj:.2f}")
            sys.stdout.flush()

            results.append((gap, rv, trades, wr, pnl, obj))
            done += 1

            elapsed = time.time() - t0
            eta = (elapsed / done) * (total - done)
            print(f"  [{done}/{total}] gap={gap} rv={rv} -> {trades}t {wr:.0f}%WR ${pnl:+.0f} ({eta:.0f}s left)",
                  file=sys.stderr, flush=True)

    # Summary: best combos
    results.sort(key=lambda x: x[5], reverse=True)
    print("\n\n=== TOP 10 COMBOS ===", file=sys.stderr)
    print(f"{'gap%':>6} {'rv':>6} {'trades':>7} {'WR':>6} {'P&L':>10} {'obj':>10}", file=sys.stderr)
    print('-' * 50, file=sys.stderr)
    for gap, rv, trades, wr, pnl, obj in results[:10]:
        print(f"{gap:>6.1f} {rv:>6.2f} {trades:>7} {wr:>5.1f}% {pnl:>+10.2f} {obj:>+10.2f}", file=sys.stderr)

    # Heatmap-style: P&L by gap × rv
    print("\n\n=== P&L HEATMAP (gap rows × rv cols) ===", file=sys.stderr)
    lookup = {(g, r): p for g, r, _, _, p, _ in results}
    header = "      " + "".join(f"{rv:>8.2f}" for rv in RV_VALUES)
    print(header, file=sys.stderr)
    for gap in GAP_VALUES:
        row = f"{gap:>5.1f} "
        for rv in RV_VALUES:
            val = lookup.get((gap, rv), 0)
            row += f"{val:>+8.0f}"
        print(row, file=sys.stderr)


if __name__ == '__main__':
    main()
