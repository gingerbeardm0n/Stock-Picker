"""Micro-pullback entries on premarket movers: does waiting for the pullback fix the entry?

A reader (u/keeganm181, r/Daytrading, Oct 2026) said Ross's main entry is NOT the first pop: he
waits for a pullback and buys the next green candle that makes a new high, which avoids the
"pop then dump below the start within 3 one-minute candles" flush. Our earlier confirmation test
(ross_confirmation_news_test.py) bought the first new premarket high after the flag and lost,
but that is not the same rule. This tests the described rule.

PRIMARY DEFINITION (fixed in advance from the comment; nothing is tuned):
  population  every hit of the hindsight-free premarket scanner (premarket_float_hits.csv)
  pullback    1-4 consecutive red 1-min bars (close < open, bars at most 3 minutes apart),
              measured from the session high before the pullback to the pullback low: depth
              between 2% and 20%
  trigger     the first later bar whose HIGH exceeds the last red bar's high by >= $0.01 and
              that traded >= 3,000 shares (only past data and that bar's own range are used)
  window      "premarket": trigger at/after the scanner flag and before 09:29
              "open": trigger 09:30-10:58 (same premarket movers, continuing past the bell)
  one trade per stock-morning per window (the first valid trigger)
Entry modes: next  = open of the following bar (what a bot that sees the trigger bar close, then
                     sends a marketable limit, can get; the honest primary)
             stop  = resting buy-stop at max(open, prior high + $0.01) filled inside the trigger
                     bar (premarket brokers only take limit orders, so this is an optimistic bound)
Costs: 0.3% per side (what every earlier test used) and 1.0% per side (premarket spreads are
       likely wider than 0.3%; see community/READING_LIST.md).
Exits: fixed hold of 10 / 30 minutes from the entry minute (last bar in the window, close), and
       Ross-style structural: stop = pullback low - $0.01, target = 2R, time exit after 30 min,
       honest fills (a stop is filled at the stop or the next bar's open, whichever is worse; gaps
       through the stop fill at the open). Trades whose stop is closer than 1% of entry are skipped
       for the structural variant only.
Statistics: bootstrap 95% CI resampling DAYS (stocks flagged the same morning are correlated).
Sensitivity variants (report only, never used to choose): S1 needs >= 2 red bars; S2 needs
pullback depth >= 5%.
Baseline: buy the first bar at the flag, same exits and costs.

Usage:  python research/analysis/scripts/premarket_pullback_test.py   (local TimescaleDB up)
"""
import os
import sys

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE, DSN  # noqa: E402

HOLDS = [10, 30]
COSTS = [0.003, 0.010]
MAXGAP = 3
MIN_TRIG_VOL = 3000
STRUCT_HOLD, STRUCT_R, MIN_RISK = 30, 2.0, 0.01
OPEN_MIN = 9 * 60 + 30
WINDOWS = {'premarket': (None, OPEN_MIN - 1), 'open': (OPEN_MIN, 11 * 60 - 1)}  # (start, end) minutes
VARIANTS = {'primary': dict(min_red=1, max_red=4, dmin=0.02, dmax=0.20),
            'S1_two_reds': dict(min_red=2, max_red=4, dmin=0.02, dmax=0.20),
            'S2_deeper': dict(min_red=1, max_red=4, dmin=0.05, dmax=0.20)}
RNG = np.random.default_rng(20261018)
BOOT = 3000


def log(*a):
    print(*a, flush=True)


def load_bars(conn):
    df = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et,
                               open, high, low, close, volume FROM ross_scanner_bars_1m""", conn)
    df['day'] = df.et.dt.date
    df['m'] = df.et.dt.hour * 60 + df.et.dt.minute
    out = {}
    for (sym, d), g in df.sort_values(['symbol', 'et']).groupby(['symbol', 'day']):
        out[(sym, d)] = (g.m.values, g.open.values, g.high.values, g.low.values, g.close.values,
                         g.volume.values)
    return out


def load_frame():
    path = os.path.join(os.path.dirname(CACHE), 'premarket_float_hits.csv')
    df = pd.read_csv(path, parse_dates=['day'])
    df['symbol'] = pd.read_csv(path, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
    df['day'] = df.day.dt.date
    df['type'] = df['type'].fillna('none')
    return df


def find_trigger(a, start_min, end_min, v):
    m, o, h, l, c, vol = a
    n = len(m)
    rh = np.maximum.accumulate(h)
    for i in range(2, n - 1):
        if m[i] < start_min or m[i] >= end_min:
            continue
        if not (c[i - 1] < o[i - 1]) or h[i] < h[i - 1] + 0.01 or vol[i] < MIN_TRIG_VOL \
                or m[i] - m[i - 1] > MAXGAP:
            continue
        r, j = 1, i - 2
        while j >= 0 and c[j] < o[j] and m[j + 1] - m[j] <= MAXGAP:
            r += 1
            j -= 1
        if r < v['min_red'] or r > v['max_red'] or j < 0:
            continue
        pb_low = l[j + 1:i].min()
        run = rh[j]
        depth = (run - pb_low) / run
        if v['dmin'] <= depth <= v['dmax']:
            return {'i': i, 'prev_high': h[i - 1], 'pb_low': pb_low, 'depth': depth, 'reds': r}
    return None


def run_trade(a, trig, mode, end_min):
    m, o, h, l, c, vol = a
    n, i = len(m), trig['i']
    if mode == 'next':
        e = i + 1
        if m[e] - m[i] > MAXGAP or m[e] > end_min:
            return None  # no fill: the next bar is too far away or past the window
        ep, me, start_k = o[e], m[e], e
    else:
        e, ep, me, start_k = i, max(o[i], trig['prev_high'] + 0.01), m[i], i + 1
    out = {'ep': ep, 'm': me}
    for hh in HOLDS:
        ks = np.where((m >= me) & (m <= me + hh - 1))[0]
        ks = ks[ks >= e]
        out[f'x{hh}'] = c[ks[-1]] if ks.size else np.nan
    stop = trig['pb_low'] - 0.01
    risk0 = ep - stop
    if risk0 / ep >= MIN_RISK:
        target = ep + STRUCT_R * risk0
        kind, fill = 'eod', c[-1]
        for k in range(start_k, n):
            if m[k] > me + STRUCT_HOLD:
                kind, fill = 'time', o[k]
                break
            if o[k] <= stop:
                kind, fill = 'gap', o[k]
                break
            if l[k] <= stop:
                kind, fill = 'stop', (min(stop, o[k + 1]) if k + 1 < n else c[k])
                break
            if h[k] >= target:
                kind, fill = 'target', (o[k + 1] if k + 1 < n else c[k])
                break
        out.update(sx=fill, stop=stop, kind=kind)
    else:
        out.update(sx=np.nan, stop=stop, kind='skip')
    return out


def net_ret(entry, exitpx, cost):
    return exitpx * (1 - cost) / (entry * (1 + cost)) - 1


def net_R(entry, exitpx, stop, cost):
    en, ex = entry * (1 + cost), exitpx * (1 - cost)
    return (ex - en) / (en - stop)


def dci(df, col):
    d = df.dropna(subset=[col])
    if len(d) < 10:
        return None
    g = d.groupby('day')[col].agg(['sum', 'count'])
    s, n = g['sum'].values, g['count'].values
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    boots = s[idx].sum(1) / n[idx].sum(1)
    return (len(d), d[col].mean(), d[col].median(), (d[col] > 0).mean(),
            np.percentile(boots, 2.5), np.percentile(boots, 97.5), len(g))


def fmt(label, s, pct=True):
    if s is None:
        return f'{label:<44} (n<10)'
    n, mean, med, pos, lo, hi, nd = s
    k, u = (100, '%') if pct else (1, 'R')
    return (f'{label:<44} n={n:>5} d={nd:>3}  mean {mean*k:+6.2f}{u}  median {med*k:+6.2f}{u}  '
            f'pos {pos:4.0%}  CI [{lo*k:+.2f}, {hi*k:+.2f}]')


def block(t, cost, structural=True, prefix=''):
    t = t.copy()
    for hh in HOLDS:
        t[f'r{hh}'] = net_ret(t.ep.values, t[f'x{hh}'].values, cost)
        log(fmt(f'{prefix}hold {hh} min @ {cost*100:.1f}%/side', dci(t, f'r{hh}')))
    if structural and 'sx' in t:
        ok = t.kind != 'skip'
        t['sp'] = np.where(ok, net_ret(t.ep.values, t.sx.values, cost), np.nan)
        t['sR'] = np.where(ok, net_R(t.ep.values, t.sx.values, t.stop.values, cost), np.nan)
        log(fmt(f'{prefix}structural stop/2R/30min, %', dci(t, 'sp')))
        log(fmt(f'{prefix}structural stop/2R/30min, R', dci(t, 'sR'), pct=False))
        kinds = t[ok].kind.value_counts(normalize=True)
        log(f'{prefix}  exits: ' + ', '.join(f'{k} {v:.0%}' for k, v in kinds.items())
            + f' | skipped (stop <1% away): {(~ok).mean():.0%}')


def main():
    conn = psycopg2.connect(DSN)
    frame = load_frame()
    bars = load_bars(conn)
    conn.close()
    rows, base, seen, ntrig = [], [], 0, {}
    for r in frame.itertuples():
        a = bars.get((r.symbol, r.day))
        if a is None or len(a[0]) < 6:
            continue
        seen += 1
        meta = dict(day=r.day, symbol=r.symbol, year=r.year, label=r.label, type=r.type)
        m, o, h, l, c, vol = a
        k0 = np.where(m >= r.flag_min)[0]
        if k0.size:
            e = int(k0[0])
            b = {'ep': o[e], 'm': m[e]}
            for hh in HOLDS:
                ks = np.where((m >= m[e]) & (m <= m[e] + hh - 1))[0]
                b[f'x{hh}'] = c[ks[-1]]
            base.append({**meta, **b})
        for wname, (s, e_end) in WINDOWS.items():
            start = r.flag_min if s is None else s
            for vname, v in VARIANTS.items():
                trig = find_trigger(a, start, e_end, v)
                if trig is None:
                    continue
                ntrig[(wname, vname)] = ntrig.get((wname, vname), 0) + 1
                for mode in ('next', 'stop'):
                    t = run_trade(a, trig, mode, e_end)
                    if t is not None:
                        rows.append({**meta, **t, 'window': wname, 'variant': vname, 'mode': mode,
                                     'depth': trig['depth'], 'reds': trig['reds']})
    T, B = pd.DataFrame(rows), pd.DataFrame(base)
    T.to_csv(os.path.join(os.path.dirname(CACHE), 'premarket_pullback_trades.csv'), index=False)

    log(f'stock-mornings with bars: {seen} | days: {frame.day.nunique()}')
    for (w, v), n in sorted(ntrig.items()):
        got = len(T[(T.window == w) & (T.variant == v) & (T['mode'] == 'next')])
        log(f'  {w:<9} {v:<12} triggers {n:>5} ({n/seen:.0%} of stock-mornings) | filled next-bar {got}')

    for c in COSTS[:1]:
        log(f'\n######## BASELINE: buy the first bar at the flag, same exits, {c*100:.1f}%/side ########')
        block(B, c, structural=False)
    log(f'\n######## BASELINE @ {COSTS[1]*100:.1f}%/side ########')
    block(B, COSTS[1], structural=False)

    for wname in WINDOWS:
        for mode in ('next', 'stop'):
            t = T[(T.window == wname) & (T.variant == 'primary') & (T['mode'] == mode)]
            tag = 'HONEST (next-bar open)' if mode == 'next' else 'OPTIMISTIC (intrabar buy-stop)'
            log(f'\n######## PRIMARY | window {wname} | entry {tag} | {len(t)} trades ########')
            block(t, COSTS[0])
            block(t, COSTS[1])

    t = T[(T.window == 'premarket') & (T.variant == 'primary') & (T['mode'] == 'next')]
    log('\n######## SPLITS: premarket window, primary, next-bar entry, 0.3%/side ########')
    for lab, sel in (('news type = catalyst', t.type == 'catalyst'), ('news type = none', t.type == 'none'),
                     ("Ross's picks (hindsight selection)", t.label == 1), ('other hits', t.label == 0)):
        log(f'--- {lab}: {len(t[sel])} trades ---')
        block(t[sel], COSTS[0], prefix='  ')
    t2 = T[(T.window == 'open') & (T.variant == 'primary') & (T['mode'] == 'next')]
    log('\n######## SPLITS: open window, primary, next-bar entry, 0.3%/side ########')
    for lab, sel in (('news type = catalyst', t2.type == 'catalyst'), ('news type = none', t2.type == 'none')):
        log(f'--- {lab}: {len(t2[sel])} trades ---')
        block(t2[sel], COSTS[0], prefix='  ')

    for vname in ('S1_two_reds', 'S2_deeper'):
        for wname in WINDOWS:
            t = T[(T.window == wname) & (T.variant == vname) & (T['mode'] == 'next')]
            log(f'\n######## SENSITIVITY {vname} | {wname} | next-bar, 0.3%/side | {len(t)} trades ########')
            block(t, COSTS[0])
    log('\nDONE')


if __name__ == '__main__':
    main()
