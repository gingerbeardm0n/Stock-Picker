"""What makes Ross Cameron's premarket pick different, and can a model find it out of sample?

Follow-up to ross_premarket_test.py, which found that on the same morning Ross's premarket
pick beat the other scanner-flagged movers by +1.0% (10 min) / +1.8% (30 min).

Population: every hit of the hindsight-free premarket scanner (cached by ross_premarket_test.py
in research/analysis/outputs/premarket/scanner_hits.pkl). Label: 1 if Ross traded that stock
that morning. All features use ONLY data up to the scanner flag time:
  gap          price at flag vs prior close
  pm_vol       premarket shares since 04:00 (log)
  rel_vol      pm_vol / prior-day volume (log)
  price        price at flag (log)
  flag_min     minutes after midnight the stock was flagged
  mom5, mom15  return over the 5 / 15 minutes before the flag
  off_high     price at flag vs premarket high so far (0 = at the high)
  dv15         dollar volume in the 15 minutes before the flag (log)
  order        how many other hits were flagged earlier that morning
  news         tier1-3 news in the 24h before the flag (stock_news; coverage is partial)

Outcome: bot buys the open of the minute after the flag; return at close of +10 / +30 minutes
less 0.3% slippage.

Evaluation is walk-forward by year (train on every year before Y, test on Y) so nothing is
ever scored on data it was fit to. Each morning the model picks its TOP-1 scanner hit; that
pick is compared with the other hits the same morning (paired by day), with simple one-feature
rules as baselines, and with Ross's actual pick.

Usage:  python research/analysis/scripts/ross_pick_model_test.py   (local TimescaleDB up)
"""
import os
import pickle
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE, DSN, ross_picks  # noqa: E402

SLIP = 0.003
HOLDS = [10, 30]
FEATURES = ['gap', 'pm_vol', 'rel_vol', 'price', 'flag_min', 'mom5', 'mom15', 'off_high', 'dv15', 'order', 'news']
RNG = np.random.default_rng(20261012)
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs'))


def log(*a):
    print(*a, flush=True)


def load_bars(conn):
    df = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et, open, high, close, volume
                        FROM ross_scanner_bars_1m""", conn)
    df['d'] = df.et.dt.date
    df['mins'] = df.et.dt.hour * 60 + df.et.dt.minute
    return {k: g.sort_values('et').reset_index(drop=True) for k, g in df.groupby(['symbol', 'd'])}


def news_flags(conn, hits):
    """1 if a tier1-3 article for the symbol was created in the 24h before the flag time."""
    try:
        news = pd.read_sql("""SELECT symbol, created_at AT TIME ZONE 'America/New_York' AS et
                              FROM stock_news WHERE news_tier IN ('tier1', 'tier2', 'tier3')
                                AND symbol = ANY(%s)""", conn, params=(list(hits.symbol.unique()),))
    except Exception as e:  # noqa: BLE001
        log(f'news unavailable: {e}')
        return np.zeros(len(hits))
    by_sym = {s: np.sort(g.et.values) for s, g in news.groupby('symbol')}
    out = []
    for r in hits.itertuples():
        t = np.datetime64(datetime(r.day.year, r.day.month, r.day.day) + timedelta(minutes=int(r.flag_min)))
        arr = by_sym.get(r.symbol)
        out.append(int(arr is not None and ((arr <= t) & (arr > t - np.timedelta64(24, 'h'))).any()))
    log(f'news coverage: {len(news):,} tier1-3 articles; {np.mean(out):.0%} of hits have news in prior 24h')
    return np.array(out)


def build(conn):
    hits = pickle.load(open(os.path.join(CACHE, 'scanner_hits.pkl'), 'rb')).reset_index(drop=True)
    prior = pickle.load(open(os.path.join(CACHE, 'prior_day.pkl'), 'rb'))
    picks, _ = ross_picks(conn)
    ross = set(zip(picks.symbol, picks.day))
    bars = load_bars(conn)
    hits['order'] = hits.groupby('day').flag_min.rank(method='min') - 1
    rows = []
    for r in hits.itertuples():
        g = bars.get((r.symbol, r.day))
        pr = prior[r.day]
        pr = pr[pr.symbol == r.symbol]
        if g is None or pr.empty:
            continue
        m = g.mins.values
        pre = np.where(m < r.flag_min)[0]
        nxt = np.where(m >= r.flag_min)[0]
        if pre.size < 3 or nxt.size == 0:
            continue
        o, c, hi, v = g.open.values, g.close.values, g.high.values, g.volume.values
        px = c[pre[-1]]

        def back(mins):
            k = np.where(m <= r.flag_min - mins)[0]
            return (px / c[k[-1]] - 1) if k.size else 0.0
        last15 = pre[m[pre] >= r.flag_min - 15]
        e = int(nxt[0])
        row = {'symbol': r.symbol, 'day': r.day, 'year': r.day.year, 'label': int((r.symbol, r.day) in ross),
               'gap': px / float(pr.prior_close.iloc[0]) - 1,
               'pm_vol': np.log1p(v[pre].sum()),
               'rel_vol': np.log1p(v[pre].sum() / max(float(pr.prior_vol.iloc[0]), 1.0)),
               'price': np.log(px), 'flag_min': r.flag_min,
               'mom5': back(5), 'mom15': back(15),
               'off_high': px / hi[pre].max() - 1,
               'dv15': np.log1p((c[last15] * v[last15]).sum()) if last15.size else 0.0,
               'order': r.order, 'flag_px': px}
        for h in HOLDS:
            j = e + h - 1
            row[f'fwd{h}'] = (c[j] * (1 - SLIP) - o[e]) / o[e] if j < len(o) else np.nan
        rows.append(row)
    df = pd.DataFrame(rows)
    df['news'] = news_flags(conn, df)
    return df


def ci(a, n=4000):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 5:
        return None
    b = RNG.choice(a, size=(n, a.size), replace=True).mean(axis=1)
    return a.size, a.mean(), np.median(a), (a > 0).mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def line(label, s):
    if s is None:
        return f'{label:<46} (n<5)'
    n, mean, med, pos, lo, hi = s
    return (f'{label:<46} n={n:>4}  mean {mean*100:+6.2f}%  median {med*100:+6.2f}%  '
            f'pos {pos:4.0%}  95% CI [{lo*100:+.2f}, {hi*100:+.2f}]')


def top1_eval(test, score_col, h, label):
    """Per day: return of the top-scored hit, and paired diff vs the mean of the other hits."""
    picked, diffs = [], []
    for d, g in test.groupby('day'):
        g = g.dropna(subset=[f'fwd{h}'])
        if len(g) < 2:
            continue
        top = g.loc[g[score_col].idxmax()]
        picked.append(top[f'fwd{h}'])
        diffs.append(top[f'fwd{h}'] - g.drop(top.name)[f'fwd{h}'].mean())
    log(line(f'{label}: top-1 pick', ci(picked)))
    log(line(f'{label}: top-1 minus other hits', ci(diffs)))


def main():
    conn = psycopg2.connect(DSN)
    path = os.path.join(CACHE, 'pick_features.pkl')
    if os.path.exists(path):
        df = pickle.load(open(path, 'rb'))
    else:
        df = build(conn)
        pickle.dump(df, open(path, 'wb'))
    conn.close()
    df.to_csv(os.path.join(OUT, 'ross_pick_features.csv'), index=False)
    log(f'hits with features: {len(df)} | Ross picks among them: {df.label.sum()} | days: {df.day.nunique()}')

    log('\n=== What differs: median feature, Ross picks vs other hits ===')
    for f in FEATURES:
        a, b = df[df.label == 1][f], df[df.label == 0][f]
        log(f'{f:<10} Ross {a.median():>9.3f}   others {b.median():>9.3f}   '
            f'(Ross mean {a.mean():.3f} vs {b.mean():.3f})')

    log('\n=== Do the Ross picks still outperform among SCANNER HITS only? (sanity) ===')
    for h in HOLDS:
        log(line(f'hold {h}: Ross picks', ci(df[df.label == 1][f'fwd{h}'])))
        log(line(f'hold {h}: other hits', ci(df[df.label == 0][f'fwd{h}'])))

    # walk-forward: train on all years before Y, score Y
    test_years = [y for y in sorted(df.year.unique()) if df[df.year < y].label.sum() >= 40]
    log(f'\nwalk-forward test years: {test_years}')
    scored = []
    for y in test_years:
        tr, te = df[df.year < y], df[df.year == y].copy()
        sc = StandardScaler().fit(tr[FEATURES])
        clf = LogisticRegression(C=0.3, max_iter=2000, class_weight='balanced')
        clf.fit(sc.transform(tr[FEATURES]), tr.label)
        te['p_ross'] = clf.predict_proba(sc.transform(te[FEATURES]))[:, 1]
        # direct model: predict the 30-min outcome itself (baseline, more overfit-prone)
        trd = tr.dropna(subset=['fwd30'])
        clf2 = LogisticRegression(C=0.3, max_iter=2000, class_weight='balanced')
        clf2.fit(sc.transform(trd[FEATURES]), (trd.fwd30 > 0).astype(int))
        te['p_up'] = clf2.predict_proba(sc.transform(te[FEATURES]))[:, 1]
        auc = roc_auc_score(te.label, te.p_ross) if te.label.nunique() == 2 else float('nan')
        log(f'  {y}: train {len(tr)} hits ({tr.label.sum()} Ross) -> test {len(te)} ({te.label.sum()} Ross), '
            f'AUC predicting Ross pick {auc:.2f}')
        scored.append(te)
        if y == test_years[-1]:
            coefs = sorted(zip(FEATURES, clf.coef_[0]), key=lambda x: -abs(x[1]))
            log('  latest model weights (standardized): ' + ', '.join(f'{f} {w:+.2f}' for f, w in coefs))
    test = pd.concat(scored)
    test['rnd'] = RNG.random(len(test))
    for f in ('gap', 'pm_vol', 'rel_vol', 'mom15', 'dv15'):
        test[f'r_{f}'] = test[f]
    test['r_early'] = -test['flag_min']

    for h in HOLDS:
        log(f'\n=== OUT-OF-SAMPLE, hold {h} min, one stock per morning ===')
        top1_eval(test, 'p_ross', h, 'Ross-imitation model')
        top1_eval(test, 'p_up', h, 'direct return model')
        for f, lab in (('r_rel_vol', 'rule: highest rel vol'), ('r_pm_vol', 'rule: highest pm volume'),
                       ('r_gap', 'rule: biggest gap'), ('r_mom15', 'rule: strongest 15-min momentum'),
                       ('r_dv15', 'rule: most $ volume last 15 min'), ('r_early', 'rule: first flagged'),
                       ('rnd', 'random hit')):
            top1_eval(test, f, h, lab)
        ross = test[test.label == 1]
        log(line("Ross's actual picks (same test years)", ci(ross[f'fwd{h}'])))
    log('\nDONE')


if __name__ == '__main__':
    main()
