"""Entry-edge test: do a strategy's entries predict upward moves, independent of exits?

Two exit sweeps (stop 3-10%, hold 1-15 bars) left scalp Trial 211 stuck at PF 0.6-0.7
under the honest sim. When no exit change moves the result, the entries are the suspect.
This script measures the entries directly: for every simulated entry, the raw price move
N bars later with NO stop, target, or trail -- just cost of entry and exit.

If the average forward return is <= 0, no exit design can rescue these entries.
If it is positive, the exits are leaving money on the table.

Two entry bases, because the sim's default ENTRY fill is 'perfect' (signal price, no
slippage) -- only exits were made honest in Gate 0:
  A. sim entry   -- the entry_price the simulator recorded
  B. real entry  -- open of the NEXT bar (what a market order sent on the signal gets)
Both exit at the close of bar entry_idx + N, less exit slippage (0.3%, the honest default).
A large A-vs-B gap means entry fills are a second source of sim optimism.

Returns are per-trade percentages, equal-weighted, so position sizing cannot confound them.
Small caps have fat tails, so mean, median, 1%-trimmed mean, and a bootstrap 95% CI on the
mean are all reported -- a positive mean driven by a handful of runners is not an edge.

Usage (local TimescaleDB must be up):
    python research/analysis/scripts/entry_edge_forward_returns.py
    python research/analysis/scripts/entry_edge_forward_returns.py 2025-01-01 2025-12-31
Per-trade rows -> research/analysis/outputs/entry_edge_<start>_<end>.csv (gitignored).
"""
import csv
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..', 'production')))
logging.disable(logging.WARNING)

from simulator.scalp_simulation import run_scalp_date_range_multi  # noqa: E402
from trading.live_scalp_runner import TRIAL_211_CONFIG  # noqa: E402
from utils.query_helpers import StockDataDB  # noqa: E402

ET = pytz.timezone('America/New_York')
HORIZONS = [1, 3, 5, 10, 15]
EXIT_SLIPPAGE = 0.003   # honest-sim default (exit_slippage_pct=0.3)
BOOT_N = 2000
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs'))


def _to_et(t):
    return t.astimezone(ET) if hasattr(t, 'astimezone') else datetime.fromisoformat(str(t)).astimezone(ET)


def _minute_key(t):
    return _to_et(t).strftime('%Y-%m-%d %H:%M')


def _market_bars(db, symbol, date):
    """Market-hours bars 9:30-11:59 ET, chronological, each with '_et'."""
    raw = db.get_minute_bars([symbol], date, start_hour=9, end_hour=12).get(symbol, [])
    out = []
    for b in raw:
        t = b.get('time')
        if t is None:
            continue
        et = _to_et(t)
        if et.hour > 9 or (et.hour == 9 and et.minute >= 30):
            b['_et'] = et
            out.append(b)
    out.sort(key=lambda b: b['_et'])
    return out


def _stats(xs, rng):
    a = np.asarray(xs, dtype=float)
    if a.size == 0:
        return None
    lo, hi = np.percentile(a, [1, 99])
    trimmed = a[(a >= lo) & (a <= hi)]
    boots = rng.choice(a, size=(BOOT_N, a.size), replace=True).mean(axis=1)
    return {
        'n': a.size,
        'mean': a.mean() * 100,
        'median': np.median(a) * 100,
        'trim': trimmed.mean() * 100 if trimmed.size else float('nan'),
        'pos': (a > 0).mean() * 100,
        'ci_lo': np.percentile(boots, 2.5) * 100,
        'ci_hi': np.percentile(boots, 97.5) * 100,
    }


def analyze(start, end, rng):
    cfg = TRIAL_211_CONFIG
    print(f"\n{'=' * 92}\nSCALP 211 entries | {start} -> {end} | exit_fill_mode={cfg.exit_fill_mode}"
          f" | entry fill_model={cfg.fill_model}", flush=True)
    res = run_scalp_date_range_multi(cfg, start, end, verbose=False)
    trades = res['trades']
    print(f"sim trades: {len(trades)} | sim P&L ${res['total_pnl']:+.2f} | PF {res['profit_factor']:.2f}", flush=True)

    fwd_a = {h: [] for h in HORIZONS}
    fwd_b = {h: [] for h in HORIZONS}
    entry_gap, mfe, mae, rows = [], [], [], []
    unmatched = 0

    with StockDataDB() as db:
        for t in trades:
            bars = _market_bars(db, t.symbol, t.date)
            key = _minute_key(t.entry_time)
            idx = next((i for i, b in enumerate(bars) if _minute_key(b['_et']) == key), None)
            if idx is None or idx + 1 >= len(bars):
                unmatched += 1
                continue

            e_sim = float(t.entry_price)
            e_real = float(bars[idx + 1]['open'])
            entry_gap.append((e_real - e_sim) / e_sim)
            row = {'date': t.date, 'symbol': t.symbol, 'entry_time': key,
                   'e_sim': e_sim, 'e_real': e_real, 'sim_pnl': t.pnl}

            for h in HORIZONS:
                j = idx + h
                if j >= len(bars):
                    continue
                exit_px = float(bars[j]['close']) * (1 - EXIT_SLIPPAGE)
                ra = (exit_px - e_sim) / e_sim
                rb = (exit_px - e_real) / e_real
                fwd_a[h].append(ra)
                fwd_b[h].append(rb)
                row[f'fwdA_{h}'] = round(ra * 100, 3)
                row[f'fwdB_{h}'] = round(rb * 100, 3)

            window = bars[idx + 1: idx + 1 + max(HORIZONS)]
            if window:
                mfe.append((max(float(b['high']) for b in window) - e_real) / e_real)
                mae.append((min(float(b['low']) for b in window) - e_real) / e_real)
            rows.append(row)

    print(f"matched {len(rows)} / {len(trades)} entries ({unmatched} unmatched or no next bar)", flush=True)

    g = _stats(entry_gap, rng)
    if g:
        print(f"\nENTRY FILL GAP (next-bar open vs sim entry price): mean {g['mean']:+.2f}%  "
              f"median {g['median']:+.2f}%  95% CI [{g['ci_lo']:+.2f}, {g['ci_hi']:+.2f}]")
        print("  positive = a real market order pays MORE than the sim assumes")

    for label, fwd in (('A  sim entry price', fwd_a), ('B  next-bar-open entry (realistic)', fwd_b)):
        print(f"\nFORWARD RETURN, net of {EXIT_SLIPPAGE*100:.1f}% exit slippage — basis {label}")
        print(f"{'bars':>5} {'n':>5} {'mean%':>7} {'median%':>8} {'trim1%':>7} {'%pos':>6} {'95% CI of mean':>20}")
        for h in HORIZONS:
            s = _stats(fwd[h], rng)
            if s:
                print(f"{h:>5} {s['n']:>5} {s['mean']:>+7.2f} {s['median']:>+8.2f} {s['trim']:>+7.2f} "
                      f"{s['pos']:>5.0f}% {'[':>3}{s['ci_lo']:+6.2f}, {s['ci_hi']:+6.2f}]")

    if mfe:
        print(f"\nEXCURSION over next {max(HORIZONS)} bars from realistic entry:")
        print(f"  max favorable (MFE): mean {np.mean(mfe)*100:+.2f}%  median {np.median(mfe)*100:+.2f}%")
        print(f"  max adverse   (MAE): mean {np.mean(mae)*100:+.2f}%  median {np.median(mae)*100:+.2f}%")

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f'entry_edge_{start}_{end}.csv')
    if rows:
        fields = sorted({k for r in rows for k in r},
                        key=lambda k: (k.startswith('fwd'), k))
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        print(f"\nper-trade rows -> {path}")


def main():
    rng = np.random.default_rng(20261002)
    if len(sys.argv) == 3:
        periods = [(sys.argv[1], sys.argv[2])]
    else:
        periods = [('2025-01-01', '2025-12-31'), ('2026-01-01', '2026-06-12')]
    for start, end in periods:
        analyze(start, end, rng)
    print("\nDONE")


if __name__ == '__main__':
    main()
