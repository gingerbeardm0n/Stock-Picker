"""Step 0 of model B: does a perfect copy of Ross's buy/sell seconds make money, and how late can it be?
Pre-registered: docs/PREREG_2026_11_ROSS_COPY_LATENCY.md.

Episodes from his 2017-18 Lightspeed order log (tick-confirmed fills only): a run of buys then a run of sells per
(day, symbol). Each fill is copied at the first SIP print at or after (his second + delay), same shares.
Net return = weighted avg sell / weighted avg buy - 1 - 2 * cost. Day-clustered bootstrap CI.
Uses the cached Alpaca SIP ticks (ross_exec_size_pilot.ticks_sz).
  python research/analysis/scripts/ross_copy_latency_test.py
"""
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'data_backfill')))
sys.path.insert(0, HERE)
from backfill_ross_ledger import ET, _client  # noqa: E402
from ross_exec_size_pilot import ticks_sz  # noqa: E402

OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs'))
DELAYS = (0, 1, 2, 5, 10, 30)
COST = 0.002  # per side (primary)
MAX_WAIT = 60
RNG = np.random.default_rng(20261120)


def secs(t):
    h, m, s = map(int, str(t).split(':'))
    return h * 3600 + m * 60 + s


def episodes():
    c = pd.read_csv(os.path.join(OUT, 'ross_imitation', 'lightspeed_logs', 'check.csv'))
    c = c[c.hit.astype(bool)].copy()
    c['side'] = c.side.replace({'SL': 'SLD'})
    c['t'] = c.time.map(secs)
    c['day'] = pd.to_datetime(c.day).dt.date
    eps = []
    for (d, sym), g in c.sort_values('t').groupby(['day', 'symbol']):
        cur = None
        for _, r in g.iterrows():
            if r.side == 'BOT':
                if cur is None or cur['sells']:
                    if cur and cur['buys'] and cur['sells']:
                        eps.append(cur)
                    cur = dict(day=d, symbol=sym, buys=[], sells=[])
                cur['buys'].append((r.t, r.price, r.filled))
            elif cur is not None:
                cur['sells'].append((r.t, r.price, r.filled))
        if cur and cur['buys'] and cur['sells']:
            eps.append(cur)
    return eps


def copy_px(tick, t_abs):
    tt, pp = tick[0], tick[1]
    i = np.searchsorted(tt, t_abs, side='left')
    if i >= len(tt) or tt[i] > t_abs + MAX_WAIT:
        return np.nan
    return pp[i]


def wavg(fills, prices=None, weighted=True):
    w = np.array([f[2] if weighted else 1.0 for f in fills], float)
    p = np.array(prices if prices is not None else [f[1] for f in fills], float)
    if np.isnan(p).any():
        return np.nan
    return (w * p).sum() / w.sum()


def boot(df, col):
    df = df[np.isfinite(df[col])]
    g = [x[col].values for _, x in df.groupby('day')]
    if len(g) < 5:
        return len(df), np.nan, np.nan, np.nan, np.nan, np.nan
    k = len(g)
    bs = [np.concatenate([g[i] for i in RNG.integers(0, k, k)]).mean() for _ in range(4000)]
    v = df[col]
    return len(df), v.mean(), v.median(), (v > 0).mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def main():
    eps = episodes()
    print(f'episodes {len(eps)} on {len({e["day"] for e in eps})} days', flush=True)
    client = _client()
    rows = []
    for e in eps:
        d = e['day']
        tick = ticks_sz(client, e['symbol'], d)
        if tick is None or not len(tick[0]):
            continue
        base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        hold = e['sells'][-1][0] - e['buys'][0][0]
        row = dict(day=d, symbol=e['symbol'], t0=e['buys'][0][0], hold_full=hold, n_buys=len(e['buys']),
                   n_sells=len(e['sells']), ross_gross=wavg(e['sells']) / wavg(e['buys']) - 1)
        for D in DELAYS:
            bp = [copy_px(tick, base + f[0] + D) for f in e['buys']]
            sp = [copy_px(tick, base + f[0] + D) for f in e['sells']]
            gross = wavg(e['sells'], sp) / wavg(e['buys'], bp) - 1
            row[f'gross_{D}'] = gross
            row[f'net_{D}'] = gross - 2 * COST
            row[f'unw_{D}'] = wavg(e['sells'], sp, False) / wavg(e['buys'], bp, False) - 1 - 2 * COST
        rows.append(row)
    r = pd.DataFrame(rows)
    os.makedirs(os.path.join(OUT, 'copy_latency'), exist_ok=True)
    r.to_csv(os.path.join(OUT, 'copy_latency', 'episodes.csv'), index=False)
    print(f'scored {len(r)} episodes (no ticks: {len(eps) - len(r)})\n')

    def table(sub, prefix, extra=0.0, title=''):
        print(title)
        print(f'  {"delay":>6} {"n":>4} {"mean":>8} {"median":>8} {"green":>6}  95% CI (day-clustered)')
        for D in DELAYS:
            s = sub.copy()
            s['x'] = s[f'{prefix}_{D}'] + extra
            n, m, med, g, lo, hi = boot(s, 'x')
            tag = '  <- PRIMARY' if (D == 0 and prefix == 'net' and extra == 0 and title.startswith('PRIMARY')) else ''
            print(f'  {D:>5}s {n:>4} {m * 100:+7.2f}% {med * 100:+7.2f}% {g:>5.0%}  [{lo * 100:+.2f}, {hi * 100:+.2f}]{tag}')
        print()

    n, m, med, g, lo, hi = boot(r, 'ross_gross')
    print(f'REFERENCE his own logged prices, no cost: n {n} mean {m * 100:+.2f}% median {med * 100:+.2f}% '
          f'green {g:.0%} CI [{lo * 100:+.2f}, {hi * 100:+.2f}]\n')
    table(r, 'net', 0, 'PRIMARY copy at SIP prints, share-weighted, 0.2%/side cost')
    print('--- robustness (pre-registered re-reports) ---\n')
    table(r, 'gross', 0, 'no cost')
    table(r, 'gross', -0.002, '0.1%/side cost')
    table(r, 'unw', 0, 'unweighted fills, 0.2%/side')
    table(r[r.hold_full <= 60], 'net', 0, 'split: fully out <= 60 s')
    table(r[r.hold_full > 60], 'net', 0, 'split: fully out > 60 s')


if __name__ == '__main__':
    main()
