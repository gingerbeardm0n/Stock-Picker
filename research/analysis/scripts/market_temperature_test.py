"""Does the premarket edge depend on a HOT small-cap market?

A reader of our r/Daytrading post (Oct 2026) said Ross Cameron's style only works in a hot
small-cap market and makes little in cold/sideways months. Ross's own self-reported stats say
the same (hot market +$3,516/trade at 72% wins vs cold -$63/trade at 54%, RC_STRATEGY_STATISTICS.md
section 6), but his "hot/cold" label comes from his own videos, so it is partly circular.

This tests it with market data, hindsight-free, on the premarket scanner hits:

  hotness (market-wide, needs the local DB): mean number of small-cap gappers per day
      (gap >= 10%, open $1-20, from daily_gappers) over the PRIOR 20 trading days, excluding today.
  hotness (scanner-based fallback, no DB): mean scanner hits per scanned day over the prior
      30 calendar days (>= 5 scanned days). Only days with a matched Ross premarket pick are
      scanned, so quiet days are under-represented. Treat as a rough proxy.
  hits_today: scanner hits that same morning. Reported for reference only: it includes flags that
      happen after any given flag, so it leaks a little.

Days are split into terciles (cold / middle / hot) by trailing hotness. Cut points use the whole
sample, which is a mild look-ahead on the thresholds only. For each tercile we report, buying the
minute after the flag (0.3% exit slippage), 10 and 30 minutes later:
  - buy every flagged stock
  - catalyst movers minus no-news movers, same morning (paired)
  - Ross's picks minus the other flagged stocks, same morning (paired)
  - Ross's picks alone

Year mix per tercile is printed because hot markets cluster in recent years.

Inputs: research/analysis/outputs/premarket_float_hits.csv (written by premarket_float_test.py).
Usage:  python research/analysis/scripts/market_temperature_test.py   (DB optional)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE, DSN  # noqa: E402
from ross_pick_model_test import ci, line, log  # noqa: E402

HOLDS = [10, 30]
TIERS = ['cold', 'middle', 'hot']


def market_hotness_db():
    import psycopg2
    conn = psycopg2.connect(DSN, connect_timeout=8)
    g = pd.read_sql("""SELECT trade_date, count(*) AS n FROM daily_gappers
                       WHERE gap_pct >= 10 AND open_price BETWEEN 1 AND 20
                       GROUP BY 1 ORDER BY 1""", conn)
    conn.close()
    s = g.assign(trade_date=pd.to_datetime(g.trade_date)).set_index('trade_date').n
    return s.rolling(20, min_periods=10).mean().shift(1)


def scanner_hotness(df):
    per_day = df.groupby('day').size()
    out = {}
    for d in per_day.index:
        w = per_day[(per_day.index < d) & (per_day.index >= d - pd.Timedelta(days=30))]
        out[d] = w.mean() if len(w) >= 5 else np.nan
    return df.day.map(out), df.day.map(per_day)


def paired(d, a_mask, b_mask, h):
    diffs = []
    for _, g in d.groupby('day'):
        a = g[a_mask.loc[g.index]][f'fwd{h}'].dropna()
        b = g[b_mask.loc[g.index]][f'fwd{h}'].dropna()
        if len(a) and len(b):
            diffs.append(a.mean() - b.mean())
    return ci(diffs)


def analyze(df, col, title):
    d = df.dropna(subset=[col]).copy()
    daily = d.groupby('day')[col].first()
    q1, q2 = daily.quantile([1 / 3, 2 / 3])
    d['tier'] = np.where(d[col] <= q1, 'cold', np.where(d[col] <= q2, 'middle', 'hot'))
    log(f'\n######## {title} ########')
    log(f'days with a value: {daily.size} | cut points: cold <= {q1:.1f} < middle <= {q2:.1f} < hot')
    mix = pd.crosstab(d.tier, d.year).reindex(TIERS)
    log('stock-mornings by tier and year:\n' + mix.to_string())
    cat, none = d.type == 'catalyst', d.type == 'none'
    ross, other = d.label == 1, d.label == 0
    for h in HOLDS:
        log(f'\n=== hold {h} min ===')
        for t in TIERS:
            x = d[d.tier == t]
            nd = x.day.nunique()
            log(f'--- {t} market: {nd} mornings, {len(x)} flagged stocks, mean hotness {x[col].mean():.1f} ---')
            log(line('buy every flagged stock', ci(x[f'fwd{h}'])))
            log(line('catalyst minus no-news (paired)', paired(x, cat, none, h)))
            log(line("Ross's picks minus other hits (paired)", paired(x, ross, other, h)))
            log(line("Ross's picks alone", ci(x[x.label == 1][f'fwd{h}'])))
            log(line('other hits alone', ci(x[x.label == 0][f'fwd{h}'])))
    return d


def within_year(d, h=10):
    log(f'\n######## SAME-YEAR CHECK (removes the era confound), hold {h} min ########')
    for y in sorted(d.year.unique()):
        x = d[d.year == y]
        tiers = [t for t in TIERS if x[x.tier == t].day.nunique() >= 15]
        if len(tiers) < 2:
            continue
        log(f'--- {y} ---')
        for t in tiers:
            sub = x[x.tier == t]
            log(f'{t} market: {sub.day.nunique()} mornings, {len(sub)} flagged stocks')
            log(line("  Ross's picks alone", ci(sub[sub.label == 1][f'fwd{h}'])))
            log(line('  Ross minus others (paired)', paired(sub, sub.label == 1, sub.label == 0, h)))
            log(line('  buy every flagged stock', ci(sub[f'fwd{h}'])))


def main():
    path = os.path.join(os.path.dirname(CACHE), 'premarket_float_hits.csv')
    df = pd.read_csv(path, parse_dates=['day'])
    df['type'] = df['type'].fillna('none')
    df['hot_hits'], df['hits_today'] = scanner_hotness(df)
    try:
        trailing = market_hotness_db()
        df['hot_mkt'] = df.day.map(trailing)
        have_db = df.hot_mkt.notna().any()
    except Exception as e:  # noqa: BLE001
        log(f'DB hotness unavailable ({type(e).__name__}: {str(e)[:80]}); using scanner-based only')
        have_db = False
    log(f'stock-mornings: {len(df)} | days: {df.day.nunique()} | years: {sorted(df.year.unique())}')
    if have_db:
        d = analyze(df, 'hot_mkt', 'MARKET-WIDE hotness: small-cap gappers/day, trailing 20 trading days')
        within_year(d, 10)
        within_year(d, 30)
    analyze(df, 'hot_hits', 'SCANNER hotness: hits per scanned day, trailing 30 calendar days')
    analyze(df, 'hits_today', 'SAME-MORNING hits (leaks slightly; reference only)')
    log('\nDONE')


if __name__ == '__main__':
    main()
