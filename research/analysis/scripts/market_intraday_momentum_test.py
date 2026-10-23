"""Market intraday momentum on SPY / QQQ: does the first half hour predict the last half hour?

Pre-registered in docs/PREREG_2026_10_MARKET_INTRADAY_MOMENTUM.md (committed before this script pulled any data).
Replication of Gao, Han, Li & Zhou (2018, JFE) on 2016-2026, entirely after the paper's 1993-2013 sample.

RULE (fixed): r_first = close of the 09:59 one-minute bar / prior official close - 1. Long if > 0, short if < 0.
Enter at the open of the 15:30 bar, exit at the official close (daily bar close). Costs 0.02%/side primary,
0.05%/side robustness. One trade per instrument per day. Bootstrap CIs resample days.

Data: Alpaca SIP raw minute bars (only the 09:59, 15:00, 15:30 and 15:59 bars are kept) and daily bars, cached in
research/analysis/outputs/intraday_momentum/ (gitignored).

Usage:  python research/analysis/scripts/market_intraday_momentum_test.py collect
        python research/analysis/scripts/market_intraday_momentum_test.py evaluate     (one look)
"""
import os
import pickle
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, TimeFrame, _client, _fetch  # noqa: E402

SYMBOLS = ['SPY', 'QQQ']
START, END = datetime(2015, 12, 28), datetime(2026, 10, 23)  # a few days early so 2016-01-04 has a prior close
FIRST_DAY = pd.Timestamp('2016-01-04').date()
COST, COST_ROBUST = 0.0002, 0.0005
KEEP = {'09:59', '15:00', '15:30', '15:59'}
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'intraday_momentum'))
CACHE = os.path.join(OUT, 'bars.pkl')
RNG = np.random.default_rng(20261023)


def log(*a):
    print(*a, flush=True)


def collect():
    os.makedirs(OUT, exist_ok=True)
    client = _client()
    minute, daily = [], []
    for sym in SYMBOLS:
        d = _fetch(client, [sym], TimeFrame.Day, ET.localize(START), ET.localize(END))
        for b in d.get(sym, []):
            daily.append((sym, b.timestamp.astimezone(ET).date(), b.open, b.close))
        for year in range(START.year, END.year + 1):
            s = ET.localize(max(START, datetime(year, 1, 1)))
            e = ET.localize(min(END, datetime(year + 1, 1, 1)))
            data = _fetch(client, [sym], TimeFrame.Minute, s, e)
            n = 0
            for b in data.get(sym, []):
                t = b.timestamp.astimezone(ET)
                if t.strftime('%H:%M') in KEEP:
                    minute.append((sym, t.date(), t.strftime('%H:%M'), b.open, b.close))
                    n += 1
            log(f'  {sym} {year}: {n} kept minute bars')
    m = pd.DataFrame(minute, columns=['symbol', 'day', 'hm', 'open', 'close'])
    dl = pd.DataFrame(daily, columns=['symbol', 'day', 'open', 'close'])
    with open(CACHE, 'wb') as f:
        pickle.dump({'minute': m, 'daily': dl}, f)
    log(f'saved {len(m)} minute rows, {len(dl)} daily rows -> {CACHE}')


def build(m, dl, sym):
    d = dl[dl.symbol == sym].sort_values('day').set_index('day')
    d['prev_close'] = d['close'].shift(1)
    mm = m[m.symbol == sym]
    piv_c = mm.pivot_table(index='day', columns='hm', values='close', aggfunc='first')
    piv_o = mm.pivot_table(index='day', columns='hm', values='open', aggfunc='first')
    df = pd.DataFrame(index=d.index)
    df['prev_close'] = d['prev_close']
    df['close'] = d['close']
    df['p0959'] = piv_c.get('09:59')
    df['o1500'] = piv_o.get('15:00')
    df['o1530'] = piv_o.get('15:30')
    df['c1559'] = piv_c.get('15:59')
    df = df[df.index >= FIRST_DAY].dropna(subset=['prev_close', 'p0959', 'o1530', 'close'])
    df['r_first'] = df.p0959 / df.prev_close - 1
    df = df[df.r_first != 0]
    df['side'] = np.sign(df.r_first)
    df['gross'] = df.side * (df.close / df.o1530 - 1)
    df['gross_1559'] = df.side * (df.c1559 / df.o1530 - 1)
    df['r_1500'] = df.o1530 / df.o1500 - 1
    absr = df.r_first.abs()
    df['hi_vol'] = absr > absr.shift(1).rolling(250, min_periods=250).quantile(2 / 3)
    df['year'] = [d.year for d in df.index]
    return df


def ci(x, n_boot=5000):
    x = np.asarray(x, float)
    if len(x) < 2:
        return np.nan, np.nan
    idx = RNG.integers(0, len(x), (n_boot, len(x)))
    means = x[idx].mean(axis=1)
    return np.percentile(means, 2.5), np.percentile(means, 97.5)


def line(label, x):
    x = np.asarray(x, float) * 100
    lo, hi = ci(x)
    log(f'{label:58s} n={len(x):5d}  mean {x.mean():+.4f}%  median {np.median(x):+.4f}%  '
        f'pos {np.mean(x > 0):4.0%}  CI [{lo:+.4f}, {hi:+.4f}]')
    return x.mean(), lo


def evaluate():
    with open(CACHE, 'rb') as f:
        c = pickle.load(f)
    res = {}
    for sym in SYMBOLS:
        df = build(c['minute'], c['daily'], sym)
        net = df.gross - 2 * COST
        net_r = df.gross - 2 * COST_ROBUST
        log(f'\n######## {sym}: sign(prior close -> 10:00) traded 15:30 -> close ########')
        log(f'days traded {len(df)} ({df.index.min()} .. {df.index.max()}), long {np.mean(df.side > 0):.0%}')
        mean, lo = line(f'{sym} net @0.02%/side', net)
        mean_r, _ = line(f'{sym} net @0.05%/side', net_r)
        years = net.groupby(df.year).mean()
        trimmed = np.sort(net.values)[:-max(1, int(round(len(net) * 0.01)))].mean()
        res[sym] = dict(n=len(df), mean=mean, lo=lo, mean_r=mean_r, years=years, trimmed=trimmed, df=df, net=net)

    s, q = res['SPY'], res['QQQ']
    pos_years = int((s['years'] > 0).sum())
    crit = [
        ('(a) SPY >= 2,000 trading days', f"{s['n']}", s['n'] >= 2000),
        ('(b) SPY mean > 0 @0.02%, CI lower > 0', f"{s['mean']:+.4f}% / {s['lo']:+.4f}%", s['mean'] > 0 and s['lo'] > 0),
        ('(c) QQQ mean > 0 @0.02%', f"{q['mean']:+.4f}%", q['mean'] > 0),
        ('(d) SPY mean > 0 @0.05%', f"{s['mean_r']:+.4f}%", s['mean_r'] > 0),
        ('(e) SPY positive in >= 6 of 11 years', f'{pos_years} of {len(s["years"])}', pos_years >= 6),
        ('(f) SPY mean > 0 without best 1% of days', f"{s['trimmed'] * 100:+.4f}%", s['trimmed'] > 0),
    ]
    log('\nCRITERIA')
    for name, val, ok in crit:
        log(f'  {name:45s} {val:24s} -> {"PASS" if ok else "FAIL"}')
    log(f'VERDICT: {"PASS" if all(ok for *_, ok in crit) else "FAIL"}')

    log('\n######## REPORT-ONLY (never used to decide) ########')
    for sym in SYMBOLS:
        df, net = res[sym]['df'], res[sym]['net']
        line(f'{sym} gross (no costs)', df.gross)
        agree = np.sign(df.r_1500) == df.side
        line(f'{sym} two-signal (15:00-15:30 agrees) @0.02%', net[agree.values])
        line(f'{sym} high-vol days (trailing top third |r_first|) @0.02%', net[df.hi_vol.values])
        line(f'{sym} exit at 15:59 bar close @0.02%', (df.gross_1559 - 2 * COST).dropna())
        line(f'{sym} excluding 2020 @0.02%', net[(df.year != 2020).values])
        line(f'{sym} long only @0.02%', net[(df.side > 0).values])
        line(f'{sym} short only @0.02%', net[(df.side < 0).values])
        log(f'  {sym} per year @0.02%: ' + '  '.join(f'{y}:{v * 100:+.3f}%' for y, v in res[sym]['years'].items()))
    log('\nDONE evaluate')


if __name__ == '__main__':
    {'collect': collect, 'evaluate': evaluate}[sys.argv[1]]()
