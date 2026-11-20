"""Ross selection edge at his EXACT pick time. Pre-registered: docs/PREREG_2026_11_ROSS_EXACT_PICK.md.

Events = Ross's first tick-confirmed buy per (day, symbol), from his order log (2017-18 recaps) and the 2022 live
Positions window. Peers = stocks a hindsight-free scanner had flagged by that second. Paired: Ross's stock minus
mean peer, entry the minute after his buy, 5/10/30 min, day-clustered bootstrap.
All data from Alpaca SIP (no DB). Caches in research/analysis/outputs/exact_pick/.
  python research/analysis/scripts/ross_exact_pick_test.py
"""
import os
import pickle
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'data_backfill')))
sys.path.insert(0, HERE)
from backfill_ross_ledger import ET, TimeFrame, _client, _fetch  # noqa: E402
from alpaca.data.timeframe import TimeFrameUnit  # noqa: E402

OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs'))
CACHE = os.path.join(OUT, 'exact_pick')
BATCH = 200
CHECK_FROM, CHECK_TO = 7 * 60, 11 * 60
MIN_GAP, MIN_VOL, MIN_PRIOR_VOL = 0.10, 100_000, 50_000
HOLDS = (5, 10, 30)
RNG = np.random.default_rng(20261120)


def log(*a):
    print(*a, flush=True)


def cached(name, fn):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    v = fn()
    pickle.dump(v, open(p, 'wb'))
    return v


def secs(t):
    h, m, s = map(int, str(t).split(':'))
    return h * 3600 + m * 60 + s


def events():
    c = pd.read_csv(os.path.join(OUT, 'ross_imitation', 'lightspeed_logs', 'check.csv'))
    c = c[c.hit.astype(bool) & (c.side == 'BOT')]
    a = pd.DataFrame({'day': pd.to_datetime(c.day).dt.date, 'symbol': c.symbol, 't': c.time.map(secs), 'src': 'recap'})
    e = pd.read_csv(os.path.join(OUT, 'ross_imitation', 'screen_fills', 'check_entries.csv'))
    e = e[(e.timing == 'clock') & (e.hit == True)]  # noqa: E712
    b = pd.DataFrame({'day': pd.to_datetime(e.day).dt.date, 'symbol': e.sym, 't': e.clock.map(secs), 'src': 'live'})
    ev = pd.concat([a, b]).sort_values('t').groupby(['day', 'symbol']).first().reset_index()
    traded = ev.groupby('day').symbol.agg(set).to_dict()  # all his buys that day (excluded from peers)
    ev = ev[(ev.t >= CHECK_FROM * 60) & (ev.t < CHECK_TO * 60)]
    return ev, traded


def prior_table(client, symbols, days):
    out = {}
    for yr in sorted({d.year for d in days}):
        dd = [d for d in days if d.year == yr]
        lo, hi = min(dd) - timedelta(days=10), max(dd)
        rows = []
        for i in range(0, len(symbols), BATCH):
            data = _fetch(client, symbols[i:i + BATCH], TimeFrame.Day,
                          ET.localize(datetime.combine(lo, datetime.min.time())),
                          ET.localize(datetime.combine(hi, datetime.min.time())))
            for sym, bars in data.items():
                rows += [(sym, b.timestamp.astimezone(ET).date(), b.close, b.volume) for b in bars]
            if (i // BATCH) % 40 == 0:
                log(f'  daily {yr}: {i + BATCH}/{len(symbols)}')
        daily = pd.DataFrame(rows, columns=['symbol', 'd', 'close', 'volume']).sort_values(['symbol', 'd'])
        for d in dd:
            p = daily[(daily.d < d) & (daily.d >= d - timedelta(days=7))].groupby('symbol').tail(1)
            out[d] = dict(zip(p.symbol, zip(p.close, p.volume)))
    return out


def scan(client, d, prior):
    pc = {s: c for s, (c, v) in prior.items() if 1 <= c <= 20 and v >= MIN_PRIOR_VOL}
    syms = sorted(pc)
    s0 = ET.localize(datetime(d.year, d.month, d.day, 4, 0))
    s1 = ET.localize(datetime(d.year, d.month, d.day, 11, 0))
    hits = []
    for i in range(0, len(syms), BATCH):
        for sym, bars in _fetch(client, syms[i:i + BATCH], TimeFrame(15, TimeFrameUnit.Minute), s0, s1).items():
            cum = 0.0
            for b in sorted(bars, key=lambda x: x.timestamp):
                et = b.timestamp.astimezone(ET)
                cum += b.volume
                end = et.hour * 60 + et.minute + 15
                if CHECK_FROM <= end <= CHECK_TO and cum >= MIN_VOL and 1 <= b.close <= 20 \
                        and b.close >= pc[sym] * (1 + MIN_GAP):
                    hits.append((sym, end, b.close / pc[sym] - 1, cum))
                    break
    return pd.DataFrame(hits, columns=['symbol', 'flag_min', 'gap', 'vol'])


def minute_bars(client, d, syms):
    s0 = ET.localize(datetime(d.year, d.month, d.day, 4, 0))
    s1 = ET.localize(datetime(d.year, d.month, d.day, 12, 0))
    out = {}
    syms = sorted(syms)
    for i in range(0, len(syms), 50):
        for sym, bars in _fetch(client, syms[i:i + 50], TimeFrame.Minute, s0, s1).items():
            m = np.array([(lambda e: e.hour * 60 + e.minute)(b.timestamp.astimezone(ET)) for b in bars])
            out[sym] = (m, np.array([b.open for b in bars]), np.array([b.close for b in bars]))
    return out


def ret(bars, m0, h):
    """Entry = open of the first bar at minute >= m0; exit = close of the bar h-1 minutes later (or last before)."""
    if bars is None:
        return np.nan
    m, o, c = bars
    i = np.searchsorted(m, m0)
    if i >= len(m) or m[i] > m0 + 2:
        return np.nan
    j = np.searchsorted(m, m[i] + h - 1, side='right') - 1
    if m[j] < m[i] + h - 1 - 3:
        return np.nan
    cost = 0.005 if m0 < 9 * 60 + 30 else 0.003
    return c[j] / o[i] - 1 - 2 * cost


def boot(df, col):
    df = df[np.isfinite(df[col])]
    g = [x[col].values for _, x in df.groupby('day')]
    if len(g) < 5:
        return len(df), np.nan, np.nan, np.nan
    k = len(g)
    bs = [np.concatenate([g[i] for i in RNG.integers(0, k, k)]).mean() for _ in range(4000)]
    return len(df), df[col].mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def main():
    ev, traded = events()
    days = sorted(ev.day.unique())
    log(f'events {len(ev)} on {len(days)} days ({ev.src.value_counts().to_dict()})')
    client = _client()
    symbols = pickle.load(open(os.path.join(OUT, 'premarket', 'universe.pkl'), 'rb'))
    prior = cached('prior', lambda: prior_table(client, symbols, days))
    rows = []
    for k, d in enumerate(days, 1):
        hits = cached(f'scan_{d}', lambda: scan(client, d, prior.get(d, {})))
        dev = ev[ev.day == d]
        bars = cached(f'bars_{d}', lambda: minute_bars(client, d, set(hits.symbol) | set(dev.symbol)))
        for _, r in dev.iterrows():
            m0 = r.t // 60 + 1
            peers = hits[(hits.flag_min <= r.t // 60) & ~hits.symbol.isin(traded[d])]
            row = dict(day=d, symbol=r.symbol, src=r.src, t=r.t, pre=r.t < 9.5 * 3600, n_peers=len(peers),
                       flagged=r.symbol in set(hits.symbol))
            for h in HOLDS:
                pr = [ret(bars.get(s), m0, h) for s in peers.symbol]
                pr = [x for x in pr if np.isfinite(x)]
                row[f'ross_{h}'] = ret(bars.get(r.symbol), m0, h)
                row[f'peer_{h}'] = np.mean(pr) if pr else np.nan
                row[f'diff_{h}'] = row[f'ross_{h}'] - row[f'peer_{h}']
            rows.append(row)
        if k % 10 == 0:
            log(f'  {k}/{len(days)} days')
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(CACHE, 'events.csv'), index=False)
    log(f'\nevents scored {len(r)}, with peers {int((r.n_peers > 0).sum())}, '
        f'Ross stock flagged by scanner {int(r.flagged.sum())}, median peers {r.n_peers.median():.0f}')
    rp = r[r.n_peers > 0]
    for name, sub in [('ALL', rp), ('premarket', rp[rp.pre]), ('after open', rp[~rp.pre]),
                      ('recap 2017-18', rp[rp.src == 'recap']), ('live 2022', rp[rp.src == 'live'])]:
        log(f'\n{name}')
        for h in HOLDS:
            for col in (f'diff_{h}', f'ross_{h}', f'peer_{h}'):
                n, m, lo, hi = boot(sub, col)
                tag = ' <- PRIMARY' if (name == 'ALL' and col == 'diff_10') else ''
                log(f'  {col:<8} n={n:>4} mean {m * 100:+6.2f}%  CI [{lo * 100:+.2f}, {hi * 100:+.2f}]{tag}')


if __name__ == '__main__':
    main()
