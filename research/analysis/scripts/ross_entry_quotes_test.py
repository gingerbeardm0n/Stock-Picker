"""Model B step 1b: do bid/ask quotes help find the second Ross buys? Pre-registered: docs/PREREG_2026_11_ROSS_ENTRY_QUOTES.md.

Starts from the strip-check rows of ross_entry_trigger_test.py (prints before s, own-price prints in [s-2, s) dropped)
and adds top-of-book quote inputs from free Alpaca SIP quotes. Version A: quotes before s. Version B (leak guard):
quotes before s-2. Primary: sealed holdout, his buy second vs 'no' seconds within 60 s, A minus prints-only, paired,
day-clustered bootstrap.
Note: Alpaca SIP quotes already carry the national best bid/offer (bid and ask exchanges differ per record), so no
rebuild is needed; "exchanges at the best ask" is therefore not available and is dropped.
  python research/analysis/scripts/ross_entry_quotes_test.py
"""
import os
import pickle
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ross_entry_trigger_test as m  # noqa: E402
from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.requests import StockQuotesRequest  # noqa: E402

m.STRIP, m.TAG = True, '_strip'
QCACHE = os.path.join(m.CACHE, 'quotes')
QFEATS = ['spread_c', 'spread_pct', 'imb', 'bsz_rel', 'asz_rel', 'ask_up5', 'ask_up15', 'since_askup', 'asz_chg5',
          'qrate5', 'at_ask15', 'mid5']
log = m.log
RNG = np.random.default_rng(20261123)


def quotes(client, sym, d):
    p = os.path.join(QCACHE, f'{sym}_{d:%Y%m%d}.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    s = m.ET.localize(datetime(d.year, d.month, d.day, 6, 50))
    e = m.ET.localize(datetime(d.year, d.month, d.day, 11, 30))
    for attempt in range(6):
        try:
            q = client.get_stock_quotes(StockQuotesRequest(symbol_or_symbols=sym, start=s, end=e,
                                                           feed=DataFeed.SIP)).data.get(sym, [])
            break
        except Exception as ex:  # noqa: BLE001
            time.sleep(2 ** attempt * (5 if '429' in str(ex) else 1))
    else:
        return None
    a = np.array([(x.timestamp.timestamp(), x.bid_price, x.bid_size, x.ask_price, x.ask_size) for x in q], float)
    if not len(a):
        a = np.zeros((0, 5))
    a = a[(a[:, 1] > 0) & (a[:, 3] > 0) & (a[:, 3] >= a[:, 1])]  # drop empty / crossed
    os.makedirs(QCACHE, exist_ok=True)
    pickle.dump(a, open(p, 'wb'))
    return a


def qfeatures(q, tick, base, secs, qlag):
    qt = q[:, 0] - base
    bid, bsz, ask, asz = q[:, 1], q[:, 2], q[:, 3], q[:, 4]
    up = np.concatenate([[0], (np.diff(ask) > 0).astype(float)])
    cum_up = np.concatenate([[0], np.cumsum(up)])
    cum_b = np.concatenate([[0], np.cumsum(bsz)])
    cum_a = np.concatenate([[0], np.cumsum(asz)])
    last_up_t = np.maximum.accumulate(np.where(up > 0, qt, -np.inf))
    cut = secs - qlag
    i = np.searchsorted(qt, cut, side='left')
    k = np.maximum(i - 1, 0)

    def j(w):
        return np.searchsorted(qt, cut - w, side='left')
    mid = (bid + ask) / 2
    f = {}
    f['spread_c'] = ask[k] - bid[k]
    f['spread_pct'] = (ask[k] - bid[k]) / mid[k]
    f['imb'] = bsz[k] / np.maximum(bsz[k] + asz[k], 1e-9)
    n300 = np.maximum(i - j(300), 1)
    f['bsz_rel'] = bsz[k] / np.maximum((cum_b[i] - cum_b[j(300)]) / n300, 1e-9)
    f['asz_rel'] = asz[k] / np.maximum((cum_a[i] - cum_a[j(300)]) / n300, 1e-9)
    f['ask_up5'] = cum_up[i] - cum_up[j(5)]
    f['ask_up15'] = cum_up[i] - cum_up[j(15)]
    f['since_askup'] = cut - last_up_t[k]
    k5 = np.maximum(j(5) - 1, 0)
    f['asz_chg5'] = asz[k] / np.maximum(asz[k5], 1e-9)
    f['qrate5'] = ((i - j(5)) / 5) / np.maximum((i - j(300)) / 300, 1e-6)
    f['mid5'] = mid[k] / mid[k5] - 1
    # buyers paying up: share of prints in [s-15, s-2) at/above the ask prevailing at that print
    t, p = tick[0] - base, tick[1]
    pa = ask[np.maximum(np.searchsorted(qt, t, side='left') - 1, 0)]
    at = (p >= pa - 1e-9).astype(float)
    cum_at = np.concatenate([[0], np.cumsum(at)])
    a0 = np.searchsorted(t, secs - 15, side='left')
    a1 = np.searchsorted(t, secs - 2, side='left')
    f['at_ask15'] = (cum_at[a1] - cum_at[a0]) / np.maximum(a1 - a0, 1)
    out = pd.DataFrame(f)
    out[(i == 0)] = np.nan
    return out


def add_quotes(client, rows, qlag):
    parts = []
    groups = list(rows.groupby(['day', 'symbol'], sort=False))
    for n, ((d, sym), g) in enumerate(groups, 1):
        q = quotes(client, sym, d)
        g = g.copy()
        if q is None or not len(q):
            for c in QFEATS:
                g[c] = np.nan
        else:
            base = m.ET.localize(datetime(d.year, d.month, d.day)).timestamp()
            qf = qfeatures(q, m.ticks_sz(client, sym, d), base, g.sec.values, qlag)
            for c in QFEATS:
                g[c] = qf[c].values
        parts.append(g)
        if n % 20 == 0:
            log(f'  quotes {n}/{len(groups)} stock-days (lag {qlag})')
    return pd.concat(parts)


def near_rank(df, col, w=60):
    """Per Ross buy: share of same stock-day 'no' seconds within w s scoring lower (ties half)."""
    res = []
    for (d, s), g in df.groupby(['day', 'symbol']):
        sec, y, sc = g.sec.values, g.y.values, g[col].values
        for t in sec[y == 1]:
            v = sc[(sec == t) & (y == 1)][0]
            neg = np.sort(sc[(y == 0) & (np.abs(sec - t) <= w)])
            if not len(neg):
                continue
            lo, hi = np.searchsorted(neg, v, 'left'), np.searchsorted(neg, v, 'right')
            res.append((d, s, t, (lo + 0.5 * (hi - lo)) / len(neg)))
    return pd.DataFrame(res, columns=['day', 'symbol', 'sec', 'r'])


def boot(r, col):
    g = [x[col].values for _, x in r.groupby('day')]
    k = len(g)
    bs = [np.concatenate([g[i] for i in RNG.integers(0, k, k)]).mean() for _ in range(4000)]
    return r[col].mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def fit_score(dev, hold, feats):
    mod = m.Model().fit(dev[feats], dev.y)
    return mod, mod.score(hold[feats])


def main():
    client = m._client()
    rows = m.build(client).sort_values(['day', 'symbol', 'sec']).reset_index(drop=True)
    log(f'rows {len(rows)} (strip inputs); fetching quotes')
    va = add_quotes(client, rows, 0)
    vb = add_quotes(client, rows, 2)
    log(f'quote coverage: {va[QFEATS[0]].notna().mean():.0%} of rows')
    rec_days = sorted(va[va.src == 'recap'].day.unique())
    cut = rec_days[int(len(rec_days) * 0.8)]
    P, A = m.FEATS, m.FEATS + QFEATS
    res = {}
    for name, data, feats in [('prints only (strip)', va, P), ('A: + quotes before s', va, A),
                              ('B: + quotes before s-2', vb, A)]:
        rec = data[data.src == 'recap']
        dev, hold = rec[rec.day < cut].copy(), rec[rec.day >= cut].copy()
        mod, hold['score'] = fit_score(dev, hold, feats)
        res[name] = dict(hold=hold, mod=mod, dev=dev, live=data[data.src == 'live'].copy())
    log(f'\nSEALED HOLDOUT (15 days from {cut}), rank skill of his buy second vs "no" seconds within w:')
    log(f'  {"w":>6} ' + ' '.join(f'{k:>26}' for k in res))
    near = {}
    for w in (15, 30, 60, 120, 100000):
        cells = []
        for k, v in res.items():
            r = near_rank(v['hold'], 'score', w)
            near[(k, w)] = r
            mm, lo, hi = boot(r, 'r')
            cells.append(f'{mm:.3f} [{lo:.2f},{hi:.2f}]')
        log(f'  {("all" if w > 9999 else str(w) + "s"):>6} ' + ' '.join(f'{c:>26}' for c in cells))

    log('\nPRIMARY (within 60 s, paired vs prints only)')
    base = near[('prints only (strip)', 60)].set_index(['day', 'symbol', 'sec']).r
    gains = {}
    for k in ('A: + quotes before s', 'B: + quotes before s-2'):
        r = near[(k, 60)].set_index(['day', 'symbol', 'sec']).r
        dd = (r - base).dropna().reset_index()
        dd.columns = ['day', 'symbol', 'sec', 'd']
        mm, lo, hi = boot(dd, 'd')
        gains[k] = (mm, lo)
        log(f'  {k:<26} gain {mm:+.3f}  CI [{lo:+.3f}, {hi:+.3f}]  n={len(dd)}')
    a_ok = gains['A: + quotes before s'][1] > 0
    b_ok = gains['B: + quotes before s-2'][0] > 0
    verdict = 'PASS' if a_ok and b_ok else ('A passes but B shows no gain -> LIKELY LEAK' if a_ok else 'FAIL')
    log(f'  A CI low > 0: {a_ok} | B gain > 0: {b_ok} -> {verdict}')

    imp = pd.Series(res['A: + quotes before s']['mod'].booster_.feature_importance('gain'), A)
    imp = imp / imp.sum()
    log('\nversion A inputs by gain share: ' + ', '.join(f'{k} {v:.0%}' for k, v in imp.sort_values(ascending=False).head(10).items()))
    log(f'  quote inputs total {imp[QFEATS].sum():.0%}')

    for k in ('prints only (strip)', 'A: + quotes before s'):
        lv = res[k]['live']
        if len(lv):
            lv['score'] = res[k]['mod'].score(lv[P if k.startswith('prints') else A])
            mm, lo, hi = boot(near_rank(lv, 'score', 100000), 'r')
            m6, l6, h6 = boot(near_rank(lv, 'score', 60), 'r')
            log(f'2022 out-of-era {k:<24} all {mm:.3f} [{lo:.2f},{hi:.2f}] | within 60 s {m6:.3f} [{l6:.2f},{h6:.2f}]')

    # money check, version A, same method as step 1
    v = res['A: + quotes before s']
    dev = v['dev']
    dev_oof = dev.copy()
    days = np.array(sorted(dev.day.unique()))
    fold = {d: i % 5 for i, d in enumerate(np.random.default_rng(20261120).permutation(days))}
    dev_oof['fold'] = dev_oof.day.map(fold)
    dev_oof['score'] = np.nan
    for f in range(5):
        tr, te = dev_oof.fold != f, dev_oof.fold == f
        dev_oof.loc[te, 'score'] = m.Model().fit(dev_oof.loc[tr, A], dev_oof.loc[tr, 'y']).score(dev_oof.loc[te, A])
    target = dev.y.sum() / dev.groupby(['day', 'symbol']).ngroups
    best = None
    for q in np.linspace(0.90, 0.99995, 120):
        thr = dev_oof.score.quantile(q)
        rate = np.mean([len(m.fires(g, thr)) for _, g in dev_oof.groupby(['day', 'symbol'])])
        if best is None or abs(rate - target) < abs(best[1] - target):
            best = (thr, rate)
    hold = v['hold']
    out = {'model A fires': [], 'Ross buy seconds (ceiling)': [], 'random seconds (chance)': []}
    for (d, sym), g in hold.groupby(['day', 'symbol']):
        tick = m.ticks_sz(client, sym, d)
        b = m.ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        out['model A fires'] += [(d, m.trade_ret(tick, b, s)) for s in m.fires(g, best[0])]
        out['Ross buy seconds (ceiling)'] += [(d, m.trade_ret(tick, b, s)) for s in g.sec[g.y == 1]]
        negs = g.sec[g.y == 0].values
        for _ in range(20):
            for s in RNG.choice(negs, size=min(len(negs), max(1, int(g.y.sum()))), replace=False):
                out['random seconds (chance)'].append((d, m.trade_ret(tick, b, s)))
    log(f'\nMONEY CHECK holdout (fires {best[1]:.2f}/stock-day on dev vs Ross {target:.2f}); +1 s, half +25 s, rest +90 s, 0.2%/side')
    for k, vv in out.items():
        r = pd.DataFrame(vv, columns=['day', 'r']).dropna()
        mm, lo, hi = boot(r, 'r')
        log(f'  {k:<28} n={len(r):>5} mean {mm * 100:+.2f}% median {r.r.median() * 100:+.2f}% '
            f'green {(r.r > 0).mean():.0%} CI [{lo * 100:+.2f}, {hi * 100:+.2f}]')


if __name__ == '__main__':
    main()
