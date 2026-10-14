"""Low float: the one Ross Cameron pillar our premarket tests never used.

Ross's five pillars: price $2-20, up 10%+, high relative volume, news, and LOW FLOAT (< ~10-20M
shares). The premarket tests (ross_premarket_test.py, premarket_news_test.py,
llm_catalyst_rating.py) covered the first four. Our stock_fundamentals float is a single
current snapshot, so it was never usable historically. This builds point-in-time share counts
from SEC filings and tests float on every hindsight-free premarket scanner hit.

Shares = dei:EntityCommonStockSharesOutstanding (cover page of every 10-Q / 10-K / 20-F),
falling back to us-gaap:CommonStockSharesOutstanding. For each hit, the value from the most
recent filing FILED BEFORE the hit's day (no hindsight); stale if the latest filing is more than
400 days old. Shares outstanding is an upper bound on float (float excludes insider and
restricted holdings), but it ranks low-float names correctly.

Ticker -> CIK: SEC company_tickers.json (current listings), then EDGAR full-text search for
tickers no longer listed (display names carry "(TICKER)").

SEC fair-access policy requires a contact in the User-Agent: set SEC_USER_AGENT, e.g.
    SEC_USER_AGENT="Stock-Picker research you@example.com"
Requests are throttled under SEC's 10/second limit; responses cache to outputs/premarket/.

Usage:  python research/analysis/scripts/premarket_float_test.py   (local TimescaleDB not needed)
"""
import os
import pickle
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE  # noqa: E402
from ross_pick_model_test import ci, line, log  # noqa: E402

UA = {'User-Agent': os.environ.get('SEC_USER_AGENT', '')}
HOLDS = [10, 30]
STALE_DAYS = 400
BUCKETS = [(0, 5e6, '<5M'), (5e6, 10e6, '5-10M'), (10e6, 20e6, '10-20M'), (20e6, 50e6, '20-50M'),
           (50e6, 1e12, '>50M')]
_last = [0.0]


def sec_get(url, **kw):
    for attempt in range(5):
        wait = 0.12 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt * 2)
            continue
        return r
    return r


def ticker_map(symbols):
    path = os.path.join(CACHE, 'sec_cik_map.pkl')
    cmap = pickle.load(open(path, 'rb')) if os.path.exists(path) else {}
    if not cmap:
        cur = sec_get('https://www.sec.gov/files/company_tickers.json').json()
        current = {v['ticker'].upper(): int(v['cik_str']) for v in cur.values()}
        cmap = {s: current[s] for s in symbols if s in current}
        pickle.dump(cmap, open(path, 'wb'))
    missing = [s for s in symbols if s not in cmap]
    tried_path = os.path.join(CACHE, 'sec_cik_tried.pkl')
    tried = pickle.load(open(tried_path, 'rb')) if os.path.exists(tried_path) else set()
    todo = [s for s in missing if s not in tried]
    log(f'CIK map: {len(cmap)} from current list; full-text search for {len(todo)} more')
    for i, s in enumerate(todo, 1):
        r = sec_get('https://efts.sec.gov/LATEST/search-index', params={'q': f'"{s}"'})
        if r.ok:
            for h in r.json().get('hits', {}).get('hits', []):
                for name in h['_source'].get('display_names', []):
                    m = re.search(rf'\(({re.escape(s)})(?:,[^)]*)?\)\s*\(CIK (\d+)\)', name)
                    if m:
                        cmap[s] = int(m.group(2))
                        break
                if s in cmap:
                    break
        tried.add(s)
        if i % 100 == 0:
            pickle.dump(cmap, open(path, 'wb'))
            pickle.dump(tried, open(tried_path, 'wb'))
            log(f'  search {i}/{len(todo)}, mapped {len(cmap)}')
    pickle.dump(cmap, open(path, 'wb'))
    pickle.dump(tried, open(tried_path, 'wb'))
    return cmap


def share_history(ciks):
    path = os.path.join(CACHE, 'sec_shares.pkl')
    hist = pickle.load(open(path, 'rb')) if os.path.exists(path) else {}
    todo = [c for c in ciks if c not in hist]
    log(f'share history: {len(hist)} cached, {len(todo)} to fetch')
    for i, cik in enumerate(todo, 1):
        rows = []
        for concept in ('dei/EntityCommonStockSharesOutstanding', 'us-gaap/CommonStockSharesOutstanding'):
            r = sec_get(f'https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/{concept}.json')
            if r.ok:
                for u in r.json().get('units', {}).get('shares', []):
                    if u.get('filed') and u.get('val'):
                        rows.append((pd.Timestamp(u['filed']).date(), float(u['val'])))
            if rows:
                break
        # same filing can report several share classes: sum per filing date
        hist[cik] = (pd.DataFrame(rows, columns=['filed', 'shares']).groupby('filed').shares.sum()
                     .sort_index() if rows else None)
        if i % 200 == 0:
            pickle.dump(hist, open(path, 'wb'))
            log(f'  shares {i}/{len(todo)}')
    pickle.dump(hist, open(path, 'wb'))
    return hist


def shares_on(hist, cik, day):
    s = hist.get(cik) if cik is not None else None
    if s is None or s.empty:
        return np.nan
    prior = s[s.index < day]
    if prior.empty or (day - prior.index[-1]).days > STALE_DAYS:
        return np.nan
    return prior.iloc[-1]


def bucket(x):
    if not np.isfinite(x):
        return 'unknown'
    for lo, hi, name in BUCKETS:
        if lo <= x < hi:
            return name
    return 'unknown'


def paired(df, a_mask, b_mask, h):
    diffs = []
    for d, g in df.groupby('day'):
        a = g[a_mask.loc[g.index]][f'fwd{h}'].dropna()
        b = g[b_mask.loc[g.index]][f'fwd{h}'].dropna()
        if len(a) and len(b):
            diffs.append(a.mean() - b.mean())
    return ci(diffs)


def main():
    if not UA['User-Agent']:
        sys.exit('set SEC_USER_AGENT (SEC fair-access policy requires a contact)')
    news_csv = os.path.join(os.path.dirname(CACHE), 'premarket_news_hits.csv')
    df = pd.read_csv(news_csv, parse_dates=['day'])
    # tickers like "NA" / "NAN" must not be parsed as missing values
    df['symbol'] = pd.read_csv(news_csv, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
    df['day'] = df.day.dt.date
    cmap = ticker_map(sorted(df.symbol.unique()))
    hist = share_history(sorted(set(cmap.values())))
    df['shares'] = [shares_on(hist, cmap.get(s), d) for s, d in zip(df.symbol, df.day)]
    df['fb'] = df.shares.map(bucket)
    df.to_csv(os.path.join(os.path.dirname(CACHE), 'premarket_float_hits.csv'), index=False)
    known = df[df.fb != 'unknown']
    log(f'\nhits: {len(df)} | with point-in-time shares: {len(known)} ({len(known)/len(df):.0%})')
    log('float buckets (all hits): ' + str(df.fb.value_counts().to_dict()))
    log('float buckets (Ross picks): ' + str(df[df.label == 1].fb.value_counts().to_dict()))
    log(f'median shares: Ross picks {known[known.label == 1].shares.median()/1e6:.1f}M vs other hits '
        f'{known[known.label == 0].shares.median()/1e6:.1f}M')

    cat = df.type == 'catalyst'
    low = df.shares < 20e6
    high = df.shares >= 50e6
    for h in HOLDS:
        log(f'\n=== hold {h} min, bot buys the minute after the flag ===')
        for _, _, name in BUCKETS:
            log(line(f'float {name}', ci(df[df.fb == name][f'fwd{h}'])))
        log(line('float unknown', ci(df[df.fb == 'unknown'][f'fwd{h}'])))
        for _, _, name in BUCKETS:
            log(line(f'  catalyst + float {name}', ci(df[cat & (df.fb == name)][f'fwd{h}'])))
        log(line('PAIRED float <20M minus >=50M, same morning', paired(df, low, high, h)))
        log(line('PAIRED catalyst+<20M minus everything else', paired(df, cat & low, ~(cat & low), h)))
        log(line('catalyst + float <10M', ci(df[cat & (df.shares < 10e6)][f'fwd{h}'])))
        log(line('Ross picks float <20M', ci(df[(df.label == 1) & low][f'fwd{h}'])))
        log(line('non-Ross hits float <20M + catalyst', ci(df[(df.label == 0) & low & cat][f'fwd{h}'])))
        top = []
        for d, g in df[cat & df.shares.notna()].groupby('day'):
            g = g.dropna(subset=[f'fwd{h}'])
            if len(g):
                top.append(g.sort_values('shares')[f'fwd{h}'].iloc[0])
        log(line('rule: lowest-float catalyst hit per morning', ci(top)))
    log('\nDONE')


if __name__ == '__main__':
    main()
