"""Model B step 1: can the tape (prints before second t) tell which second Ross starts a trade?
Pre-registered: docs/PREREG_2026_11_ROSS_ENTRY_TRIGGER.md.

Yes = first buy second of each episode in his 2017-18 order log (tick-confirmed). No = every other second with >= 1
print on the same stock-day, 07:00-11:30, not within 3 s of any of his buys. Features from prints strictly before t.
LightGBM, fixed settings. Dev = first 80% of days by date (5-fold CV grouped by day), sealed holdout = last 20%.
Score = rank skill: per Ross-buy second, share of same stock-day 'no' seconds scoring lower (ties 0.5), averaged;
95% CI by day-clustered bootstrap. Uses cached Alpaca SIP ticks + Alpaca daily bars (prior close).
  python research/analysis/scripts/ross_entry_trigger_test.py
"""
import os
import pickle
import sys
from datetime import datetime, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'data_backfill')))
sys.path.insert(0, HERE)
from backfill_ross_ledger import ET, TimeFrame, _client, _fetch  # noqa: E402
from ross_exec_size_pilot import ticks_sz  # noqa: E402
from ross_copy_latency_test import episodes, secs  # noqa: E402

OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs'))
CACHE = os.path.join(OUT, 'entry_trigger')
T0, T1 = 7 * 3600, 11 * 3600 + 30 * 60
EXCL = 3
COST = 0.002
PARAMS = dict(objective='binary', max_depth=3, num_leaves=8, learning_rate=0.05, verbose=-1, seed=0)
N_TREES = 200


class Model:
    """LightGBM native API; class_weight='balanced' == positives weighted by n_neg / n_pos."""

    def fit(self, X, y):
        y = np.asarray(y)
        w = np.where(y == 1, (y == 0).sum() / max((y == 1).sum(), 1), 1.0)
        self.booster_ = lgb.train(PARAMS, lgb.Dataset(X, y, weight=w), num_boost_round=N_TREES)
        return self

    def score(self, X):
        return self.booster_.predict(X)
FEATS = ['hod_dist', 'since_high', 'gap', 'round_dist', 'half_dist', 'ret5', 'ret15', 'ret60',
         'n5', 'n15', 'n60', 'v5', 'v15', 'v60', 'upt15', 'avg_sz60', 'vwap_dist', 'tod']
RNG = np.random.default_rng(20261120)


def log(*a):
    print(*a, flush=True)


def prior_close(client, sym, d):
    p = os.path.join(CACHE, 'prior', f'{sym}_{d}.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    bars = _fetch(client, [sym], TimeFrame.Day, ET.localize(datetime.combine(d - timedelta(days=10), datetime.min.time())),
                  ET.localize(datetime.combine(d, datetime.min.time()))).get(sym, [])
    prev = [b.close for b in bars if b.timestamp.astimezone(ET).date() < d]
    v = prev[-1] if prev else np.nan
    os.makedirs(os.path.dirname(p), exist_ok=True)
    pickle.dump(v, open(p, 'wb'))
    return v


def features(tick, base, pc, extra_secs):
    """One row per candidate second: seconds with >= 1 print in [T0, T1) plus extra_secs (Ross seconds)."""
    t, p, z = tick
    rel = t - base
    cand = np.unique(np.concatenate([np.floor(rel[(rel >= T0) & (rel < T1)]).astype(int),
                                     np.asarray(extra_secs, int)]))
    cum_v = np.concatenate([[0], np.cumsum(z)])
    cum_pv = np.concatenate([[0], np.cumsum(z * p)])
    up = np.concatenate([[0], (np.diff(p) > 0).astype(float)])
    cum_up = np.concatenate([[0], np.cumsum(up)])
    hod = np.maximum.accumulate(p)
    is_new = np.concatenate([[True], p[1:] > hod[:-1]])
    last_new_t = np.maximum.accumulate(np.where(is_new, rel, -np.inf))
    i = np.searchsorted(rel, cand, side='left')  # prints strictly before second
    ok = i > 0
    cand, i = cand[ok], i[ok]
    k = i - 1
    last = p[k]

    def idx(w):
        return np.searchsorted(rel, cand - w, side='left')

    def px_at(w):
        j = idx(w) - 1
        return np.where(j >= 0, p[np.maximum(j, 0)], np.nan)
    f = {}
    f['hod_dist'] = last / hod[k] - 1
    f['since_high'] = cand - last_new_t[k]
    f['gap'] = last / pc - 1 if pc and np.isfinite(pc) else np.full(len(cand), np.nan)
    f['round_dist'] = np.ceil(last + 1e-9) - last
    f['half_dist'] = np.ceil(last * 2 + 1e-9) / 2 - last
    for w in (5, 15, 60):
        f[f'ret{w}'] = last / px_at(w) - 1
    base_n = (i - idx(300)) / 300.0
    base_v = (cum_v[i] - cum_v[idx(300)]) / 300.0
    for w in (5, 15, 60):
        j = idx(w)
        f[f'n{w}'] = ((i - j) / w) / np.maximum(base_n, 1e-6)
        f[f'v{w}'] = ((cum_v[i] - cum_v[j]) / w) / np.maximum(base_v, 1e-6)
    j15 = idx(15)
    f['upt15'] = (cum_up[i] - cum_up[j15]) / np.maximum(i - j15, 1)
    j60 = idx(60)
    f['avg_sz60'] = (cum_v[i] - cum_v[j60]) / np.maximum(i - j60, 1)
    j_open = np.searchsorted(rel, 4 * 3600)
    f['vwap_dist'] = last / ((cum_pv[i] - cum_pv[j_open]) / np.maximum(cum_v[i] - cum_v[j_open], 1)) - 1
    f['tod'] = cand / 3600.0
    df = pd.DataFrame(f)
    df['sec'] = cand
    return df


def build(client):
    p = os.path.join(CACHE, 'rows.pkl')
    if os.path.exists(p):
        return pickle.load(open(p, 'rb'))
    c = pd.read_csv(os.path.join(OUT, 'ross_imitation', 'lightspeed_logs', 'check.csv'))
    c = c[c.hit.astype(bool) & (c.side == 'BOT')]
    c['day'] = pd.to_datetime(c.day).dt.date
    allbuys = c.groupby(['day', 'symbol']).time.agg(lambda s: [secs(x) for x in s]).to_dict()
    starts = {}
    for e in episodes():
        starts.setdefault((e['day'], e['symbol']), []).append(e['buys'][0][0])
    live = pd.read_csv(os.path.join(OUT, 'ross_imitation', 'screen_fills', 'check_entries.csv'))
    live = live[live.timing.isin(['clock', 'tick-fit']) & (live.hit == True)]  # noqa: E712
    live['day'] = pd.to_datetime(live.day).dt.date
    lstarts = live.groupby(['day', 'sym']).clock.agg(lambda s: [secs(x) for x in s]).to_dict()
    jobs = [(k, v, allbuys.get(k, v), 'recap') for k, v in starts.items()] + \
           [(k, v, v, 'live') for k, v in lstarts.items()]
    out = []
    for n, ((d, sym), pos, buys, src) in enumerate(jobs, 1):
        pos = [s for s in pos if T0 <= s < T1]
        if not pos:
            continue
        tick = ticks_sz(client, sym, d)
        if tick is None or not len(tick[0]):
            continue
        base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        df = features(tick, base, prior_close(client, sym, d), pos)
        df['y'] = df.sec.isin(pos).astype(int)
        near = np.zeros(len(df), bool)
        for b in buys:
            near |= np.abs(df.sec.values - b) <= EXCL
        df = df[(df.y == 1) | ~near]
        df['day'], df['symbol'], df['src'] = d, sym, src
        out.append(df)
        if n % 25 == 0:
            log(f'  built {n}/{len(jobs)} stock-days')
    rows = pd.concat(out, ignore_index=True)
    os.makedirs(CACHE, exist_ok=True)
    pickle.dump(rows, open(p, 'wb'))
    return rows


def rank_skill(df, col):
    """Per Ross second: share of same stock-day 'no' seconds scoring lower (ties half). Returns per-positive frame."""
    res = []
    for (d, s), g in df.groupby(['day', 'symbol']):
        neg = np.sort(g.loc[g.y == 0, col].values)
        if not len(neg):
            continue
        for v in g.loc[g.y == 1, col].values:
            lo = np.searchsorted(neg, v, 'left')
            hi = np.searchsorted(neg, v, 'right')
            res.append((d, (lo + 0.5 * (hi - lo)) / len(neg)))
    return pd.DataFrame(res, columns=['day', 'r'])


def boot_mean(r, col='r'):
    g = [x[col].values for _, x in r.groupby('day')]
    k = len(g)
    if k < 3:
        return r[col].mean(), np.nan, np.nan
    bs = [np.concatenate([g[i] for i in RNG.integers(0, k, k)]).mean() for _ in range(4000)]
    return r[col].mean(), np.percentile(bs, 2.5), np.percentile(bs, 97.5)


def report(name, r):
    m, lo, hi = boot_mean(r)
    log(f'  {name:<34} n={len(r):>4} rank skill {m:.3f}  CI [{lo:.3f}, {hi:.3f}]')
    return m, lo, hi


def rule(df):
    return ((df.hod_dist >= 0) & (df.v15 >= 3)).astype(float)


def fires(g, thr, gap=60):
    out, last = [], -1e9
    for s, sc in zip(g.sec.values, g.score.values):
        if sc >= thr and s - last >= gap:
            out.append(s)
            last = s
    return out


def trade_ret(tick, base, s):
    t = tick[0] - base
    p = tick[1]

    def px(x):
        i = np.searchsorted(t, x, 'left')
        return p[i] if i < len(t) and t[i] <= x + 60 else np.nan
    b = px(s + 1)
    return 0.5 * (px(s + 1 + 25) + px(s + 1 + 90)) / b - 1 - 2 * COST


def main():
    client = _client()
    rows = build(client)
    rows = rows.sort_values(['day', 'symbol', 'sec']).reset_index(drop=True)
    rec, live = rows[rows.src == 'recap'], rows[rows.src == 'live']
    days = sorted(rec.day.unique())
    cut = days[int(len(days) * 0.8)]
    dev, hold = rec[rec.day < cut].copy(), rec[rec.day >= cut].copy()
    log(f'recap stock-days {rec.groupby(["day", "symbol"]).ngroups}, yes {int(rec.y.sum())}, no {int((rec.y == 0).sum())}')
    log(f'dev days {len([d for d in days if d < cut])} (yes {int(dev.y.sum())}), holdout days '
        f'{len([d for d in days if d >= cut])} from {cut} (yes {int(hold.y.sum())}); live 2022 yes {int(live.y.sum())}')

    # 5-fold CV on dev, grouped by day
    ddays = np.array(sorted(dev.day.unique()))
    fold = {d: i % 5 for i, d in enumerate(RNG.permutation(ddays))}
    dev['fold'] = dev.day.map(fold)
    dev['score'] = np.nan
    for k in range(5):
        tr, te = dev.fold != k, dev.fold == k
        m = Model().fit(dev.loc[tr, FEATS], dev.loc[tr, 'y'])
        dev.loc[te, 'score'] = m.score(dev.loc[te, FEATS])
    dev['rule'] = rule(dev)
    log('\nDEV (cross-validated, days never seen in training)')
    report('model', rank_skill(dev, 'score'))
    report('baseline rule (new high + 3x vol)', rank_skill(dev, 'rule'))

    model = Model().fit(dev[FEATS], dev.y)
    imp = pd.Series(model.booster_.feature_importance('gain'), FEATS).sort_values(ascending=False)
    log('\ninputs the model leans on (gain share): ' +
        ', '.join(f'{k} {v / imp.sum():.0%}' for k, v in imp.head(8).items()))

    hold['score'] = model.score(hold[FEATS])
    hold['rule'] = rule(hold)
    log('\nSEALED HOLDOUT')
    hm, hlo, _ = report('model  <- PRIMARY', rank_skill(hold, 'score'))
    rm, _, _ = report('baseline rule', rank_skill(hold, 'rule'))
    log(f'  PRIMARY: CI low > 0.5: {hlo > 0.5} | model > rule: {hm > rm} -> {"PASS" if hlo > 0.5 and hm > rm else "FAIL"}')

    if len(live):
        live = live.copy()
        live['score'] = model.score(live[FEATS])
        live['rule'] = rule(live)
        log('\nOUT-OF-ERA 2022 live entries (report only)')
        report('model', rank_skill(live, 'score'))
        report('baseline rule', rank_skill(live, 'rule'))

    # money check: threshold on dev OOF so fires/stock-day ~ Ross starts/stock-day
    target = dev.y.sum() / dev.groupby(['day', 'symbol']).ngroups
    best = None
    for q in np.linspace(0.90, 0.99995, 120):
        thr = dev.score.quantile(q)
        rate = np.mean([len(fires(g, thr)) for _, g in dev.groupby(['day', 'symbol'])])
        if best is None or abs(rate - target) < abs(best[1] - target):
            best = (thr, rate)
    thr = best[0]
    log(f'\nMONEY CHECK on holdout (threshold fires {best[1]:.2f}/stock-day on dev vs Ross {target:.2f}); '
        f'buy +1 s, sell half +25 s, rest +90 s, 0.2%/side')
    res = {'model fires': [], 'Ross buy seconds (ceiling)': [], 'random seconds (chance)': []}
    for (d, sym), g in hold.groupby(['day', 'symbol']):
        tick = ticks_sz(client, sym, d)
        base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        f = fires(g, thr)
        res['model fires'] += [(d, trade_ret(tick, base, s)) for s in f]
        res['Ross buy seconds (ceiling)'] += [(d, trade_ret(tick, base, s)) for s in g.sec[g.y == 1]]
        negs = g.sec[g.y == 0].values
        for _ in range(20):
            for s in RNG.choice(negs, size=min(len(negs), max(1, int(g.y.sum()))), replace=False):
                res['random seconds (chance)'].append((d, trade_ret(tick, base, s)))
    for k, v in res.items():
        r = pd.DataFrame(v, columns=['day', 'r']).dropna()
        if len(r) < 3:
            log(f'  {k:<28} n={len(r)}')
            continue
        m, lo, hi = boot_mean(r)
        log(f'  {k:<28} n={len(r):>5} mean {m * 100:+.2f}% median {r.r.median() * 100:+.2f}% '
            f'green {(r.r > 0).mean():.0%} CI [{lo * 100:+.2f}, {hi * 100:+.2f}]')


if __name__ == '__main__':
    main()
