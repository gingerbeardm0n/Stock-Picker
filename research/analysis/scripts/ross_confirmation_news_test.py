"""Two follow-ups to ross_pick_model_test.py: does CONFIRMATION or NEWS explain Ross's premarket edge?

The pick model showed bar features at the scanner flag predict WHICH mover Ross trades
(AUC ~0.85) but its top pick loses money. Two candidate explanations, tested here:

A. CONFIRMATION (mechanizable with data we have). Ross often buys after the flag, once the
   stock holds and pushes higher. Rule: after a stock is flagged, wait for the first minute
   (before 09:30) whose high breaks the premarket high-so-far at flag time. Two fills:
     stop  - buy-stop at max(that minute's open, old high + $0.01), plus 0.3% slippage
     late  - open of the following minute (conservative)
   Exits: close of +10 / +30 minutes from entry, less 0.3% slippage.
   Groups, scored on years the look-alike model never trained on (walk-forward):
     all hits / top-3 Ross look-alikes per morning / Ross's actual picks,
   each confirmed vs. bought straight at the flag.

B. NEWS (needs data we lack today). The corpus summaries record NEWS yes/no per trade.
   Among Ross's premarket picks, do the news-driven ones carry the edge?
   Score = average forward return of a random entry from his estimated pick time to 09:30
   (same metric as ross_premarket_test.py test C), and the flag-time forward return.

Usage:  python research/analysis/scripts/ross_confirmation_news_test.py   (local TimescaleDB up)
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd
import psycopg2
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE, DSN, OPEN, ross_picks, window_mean  # noqa: E402
from ross_pick_model_test import FEATURES, ci, line, load_bars, log  # noqa: E402

SLIP = 0.003
HOLDS = [10, 30]
TOP_K = 3


def confirmed_entry(g, flag_min, mode):
    """Index and price of the confirmed entry, or None if no new premarket high before 09:30."""
    m, o, h = g.mins.values, g.open.values, g.high.values
    pre = np.where(m < flag_min)[0]
    if pre.size == 0:
        return None
    level = h[pre].max()
    after = np.where((m >= flag_min) & (m < OPEN))[0]
    for i in after:
        if h[i] > level:
            if mode == 'stop':
                return i, max(o[i], level + 0.01) * (1 + SLIP)
            if i + 1 < len(o):
                return i + 1, o[i + 1] * (1 + SLIP)
            return None
        level = max(level, h[i])  # it is a running premarket high
    return None


def flag_entry(g, flag_min):
    idx = np.where(g.mins.values >= flag_min)[0]
    return (int(idx[0]), g.open.values[idx[0]] * (1 + SLIP)) if idx.size else None


def fwd(g, entry, h):
    if entry is None:
        return np.nan
    i, px = entry
    j = i + h - 1
    return (g.close.values[j] * (1 - SLIP) - px) / px if j < len(g) else np.nan


def walk_forward_scores(df):
    years = [y for y in sorted(df.year.unique()) if df[df.year < y].label.sum() >= 40]
    out = []
    for y in years:
        tr, te = df[df.year < y], df[df.year == y].copy()
        sc = StandardScaler().fit(tr[FEATURES])
        clf = LogisticRegression(C=0.3, max_iter=2000, class_weight='balanced')
        clf.fit(sc.transform(tr[FEATURES]), tr.label)
        te['p_ross'] = clf.predict_proba(sc.transform(te[FEATURES]))[:, 1]
        out.append(te)
    return pd.concat(out)


def test_confirmation(conn):
    feats = pickle.load(open(os.path.join(CACHE, 'pick_features.pkl'), 'rb'))
    hits = pickle.load(open(os.path.join(CACHE, 'scanner_hits.pkl'), 'rb'))
    df = feats.merge(hits[['symbol', 'day', 'flag_min']], on=['symbol', 'day'], how='left',
                     suffixes=('', '_h'))
    if 'flag_min_h' in df:
        df['flag_min'] = df['flag_min_h']
    scored = walk_forward_scores(df)
    scored['rank'] = scored.groupby('day').p_ross.rank(ascending=False, method='first')
    bars = load_bars(conn)
    log(f'\n##### A. CONFIRMATION — out-of-sample years {sorted(scored.year.unique())} #####')
    rows = []
    for r in scored.itertuples():
        g = bars.get((r.symbol, r.day))
        if g is None:
            continue
        fe = flag_entry(g, r.flag_min)
        cs = confirmed_entry(g, r.flag_min, 'stop')
        cl = confirmed_entry(g, r.flag_min, 'late')
        row = {'label': r.label, 'top': r.rank <= TOP_K, 'confirmed': cs is not None,
               'wait': (g.mins.values[cs[0]] - r.flag_min) if cs else np.nan}
        for h in HOLDS:
            row[f'flag{h}'] = fwd(g, fe, h)
            row[f'stop{h}'] = fwd(g, cs, h)
            row[f'late{h}'] = fwd(g, cl, h)
        rows.append(row)
    res = pd.DataFrame(rows)
    for name, sel in (('all scanner hits', res.index == res.index),
                      (f'top-{TOP_K} Ross look-alikes per morning', res.top),
                      ("Ross's actual picks", res.label == 1)):
        d = res[sel]
        log(f'\n--- {name}: {len(d)} stock-mornings, {d.confirmed.mean():.0%} confirmed '
            f'(median wait {d.wait.median():.0f} min) ---')
        for h in HOLDS:
            log(line(f'buy at flag, hold {h}', ci(d[f'flag{h}'])))
            log(line(f'confirmed buy-stop, hold {h}', ci(d[d.confirmed][f'stop{h}'])))
            log(line(f'confirmed next-minute, hold {h}', ci(d[d.confirmed][f'late{h}'])))
            log(line(f'  same stocks bought at flag, hold {h}', ci(d[d.confirmed][f'flag{h}'])))
            log(line(f'  never confirmed, bought at flag, hold {h}', ci(d[~d.confirmed][f'flag{h}'])))


def test_news(conn):
    log('\n##### B. NEWS — Ross premarket picks, news vs no news (from corpus summaries) #####')
    picks, ross_bars = ross_picks(conn)
    ledger = pd.read_sql("""SELECT symbol, upload_date, cells FROM ross_trade_ledger
                            WHERE status = 'matched'""", conn)
    news = {}
    for r in ledger.itertuples():
        if len(r.cells) > 5:
            flag = r.cells[5].strip().lower()
            if flag in ('yes', 'no'):
                news.setdefault(r.symbol, []).append((r.upload_date, flag))
    def news_for(sym, day):
        best = None
        for up, flag in news.get(sym, []):
            if 0 <= (up - day).days <= 4:
                best = flag if best is None or flag == 'yes' else best
        return best
    picks['news'] = [news_for(s, d) for s, d in zip(picks.symbol, picks.day)]
    log(f'premarket picks with a news field: {picks.news.notna().sum()}/{len(picks)} '
        f'(yes {(picks.news == "yes").sum()}, no {(picks.news == "no").sum()})')
    for h in HOLDS:
        for flag in ('yes', 'no'):
            sel = picks[picks.news == flag]
            vals = [window_mean(ross_bars[(r.symbol, r.day)], r.pick_min, OPEN, h) for r in sel.itertuples()]
            log(line(f'news={flag}: random entry pick->9:30, hold {h}', ci(vals)))
    # compare with the other-hits baseline from the same mornings
    hits = pickle.load(open(os.path.join(CACHE, 'scanner_hits.pkl'), 'rb'))
    scan_bars = load_bars(conn)
    for h in HOLDS:
        for flag in ('yes', 'no'):
            diffs = []
            for d, grp in picks[picks.news == flag].groupby('day'):
                st = int(grp.pick_min.min())
                rv = [window_mean(ross_bars[(r.symbol, d)], st, OPEN, h) for r in grp.itertuples()]
                cands = hits[(hits.day == d) & (hits.flag_min <= st) & (~hits.symbol.isin(grp.symbol))]
                sv = [window_mean(scan_bars[(s, d)], st, OPEN, h) for s in cands.symbol if (s, d) in scan_bars]
                rv, sv = [x for x in rv if np.isfinite(x)], [x for x in sv if np.isfinite(x)]
                if rv and sv:
                    diffs.append(np.mean(rv) - np.mean(sv))
            log(line(f'news={flag}: PAIRED vs other hits, hold {h}', ci(diffs)))


def main():
    conn = psycopg2.connect(DSN)
    test_confirmation(conn)
    test_news(conn)
    conn.close()
    log('\nDONE')


if __name__ == '__main__':
    main()
