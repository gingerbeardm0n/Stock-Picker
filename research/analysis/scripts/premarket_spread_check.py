"""How wide are premarket bid-ask spreads on the stocks our scanner flags?

Every backtest so far charged 0.3% per side. Crossing the spread costs half the quoted spread,
plus market impact and queue/latency slippage, so 0.3% per side is only realistic if typical
quoted spreads are well under ~0.6%. Research notes (community/READING_LIST.md) suggested
premarket spreads on $2-20 gappers could be several times wider. This measures them.

For a stratified sample of scanner hits (up to PER_YEAR per year), pull Alpaca SIP historical
quotes for the 2 minutes after the flag time (the moment a bot would decide). The first valid
quote (bid > 0, ask > bid) gives the spread a bot would face; the median over the window shows
how stable it is. For a subset (OPEN_PER_YEAR per year) the same stock is also sampled at 09:45,
after the open, to see how much the spread tightens.

Relative spread = (ask - bid) / mid. Per-side cost of crossing = half of that.
Quotes with a relative spread above 25% are counted as "broken" and reported separately.
Hits with no valid quote in the window are counted too: no quote = no fill.

Results cache to research/analysis/outputs/premarket/spread_samples.csv (resumable).
Usage:  python research/analysis/scripts/premarket_spread_check.py   (no DB needed)
"""
import os
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz
from dotenv import load_dotenv

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE  # noqa: E402

ET = pytz.timezone('America/New_York')
PER_YEAR, OPEN_PER_YEAR = 200, 100
WINDOW_MIN, LIMIT, SLEEP = 2, 500, 0.33
BROKEN = 0.25
OUT = os.path.join(CACHE, 'spread_samples.csv')
RNG_SEED = 20261018


def log(*a):
    print(*a, flush=True)


def quote_stats(client, sym, day, minute):
    start = ET.localize(datetime(day.year, day.month, day.day) + timedelta(minutes=int(minute)))
    for attempt in range(6):
        try:
            q = client.get_stock_quotes(StockQuotesRequest(
                symbol_or_symbols=sym, start=start, end=start + timedelta(minutes=WINDOW_MIN),
                limit=LIMIT, feed=DataFeed.SIP)).data.get(sym, [])
            break
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if 'invalid' in msg or '404' in msg or 'not found' in msg:
                return {'n_quotes': 0, 'n_valid': 0}
            time.sleep(2 ** attempt * 2)
            q = None
    if q is None:
        return {'n_quotes': -1, 'n_valid': 0}
    valid = [x for x in q if x.bid_price > 0 and x.ask_price > x.bid_price]
    if not valid:
        return {'n_quotes': len(q), 'n_valid': 0}
    mid = lambda x: (x.ask_price + x.bid_price) / 2  # noqa: E731
    sp = np.array([(x.ask_price - x.bid_price) / mid(x) for x in valid])
    good = sp[sp <= BROKEN]
    return {'n_quotes': len(q), 'n_valid': len(valid), 'first_spread': sp[0],
            'median_spread': float(np.median(sp)), 'broken_share': float((sp > BROKEN).mean()),
            'good_median': float(np.median(good)) if good.size else np.nan,
            'mid': mid(valid[0]), 'first_bid_size': valid[0].bid_size, 'first_ask_size': valid[0].ask_size}


def load_sample():
    path = os.path.join(os.path.dirname(CACHE), 'premarket_float_hits.csv')
    df = pd.read_csv(path, parse_dates=['day'])
    df['symbol'] = pd.read_csv(path, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
    df['day'] = df.day.dt.date
    df['type'] = df['type'].fillna('none')
    df = df[df.flag_min < 570]
    parts = []
    for y, g in df.groupby('year'):
        s = g.sample(min(len(g), PER_YEAR), random_state=RNG_SEED).copy()
        s['open_too'] = np.arange(len(s)) < OPEN_PER_YEAR
        parts.append(s)
    return pd.concat(parts)[['symbol', 'day', 'year', 'flag_min', 'label', 'type', 'open_too']]


def collect(sample):
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    client = StockHistoricalDataClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])
    done = pd.read_csv(OUT, parse_dates=['day']) if os.path.exists(OUT) else pd.DataFrame()
    if len(done):
        done['symbol'] = pd.read_csv(OUT, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
        done['day'] = done.day.dt.date
    have = set(zip(done.symbol, done.day)) if len(done) else set()
    rows = done.to_dict('records') if len(done) else []
    todo = [r for r in sample.itertuples() if (r.symbol, r.day) not in have]
    log(f'sample {len(sample)} stock-mornings | cached {len(have)} | to fetch {len(todo)}')
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        pre = quote_stats(client, r.symbol, r.day, r.flag_min)
        time.sleep(SLEEP)
        row = {'symbol': r.symbol, 'day': r.day, 'year': r.year, 'flag_min': r.flag_min,
               'label': r.label, 'type': r.type, **{f'pre_{k}': v for k, v in pre.items()}}
        if r.open_too:
            op = quote_stats(client, r.symbol, r.day, 9 * 60 + 45)
            time.sleep(SLEEP)
            row.update({f'open_{k}': v for k, v in op.items()})
        rows.append(row)
        if i % 100 == 0 or i == len(todo):
            pd.DataFrame(rows).to_csv(OUT, index=False)
            log(f'  {i}/{len(todo)} ({time.time() - t0:.0f}s)')
    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    df['symbol'] = df.symbol.astype(str)
    return df


def pct(a, q):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return np.percentile(a, q) * 100 if a.size else np.nan


def dist(label, s):
    s = pd.Series(s).dropna()
    if len(s) < 5:
        return f'{label:<30} (n<5)'
    return (f'{label:<30} n={len(s):>4}  p10 {pct(s,10):5.2f}%  p25 {pct(s,25):5.2f}%  median {pct(s,50):5.2f}%  '
            f'p75 {pct(s,75):5.2f}%  p90 {pct(s,90):5.2f}%  >1% {np.mean(s > 0.01):4.0%}  >2% {np.mean(s > 0.02):4.0%}')


def summarize(df):
    n = len(df)
    ok = df[df.pre_n_valid > 0]
    log(f'\nsampled stock-mornings: {n} | with a valid quote in the 2 min after the flag: {len(ok)} '
        f'({len(ok)/n:.0%}) | no valid quote: {n - len(ok)} ({(n-len(ok))/n:.0%})')
    sp = ok.pre_first_spread
    clean = ok[ok.pre_first_spread <= BROKEN]
    log(f'broken first quotes (spread > {BROKEN:.0%}): {(sp > BROKEN).mean():.1%} of quoted')
    log('\n=== RELATIVE SPREAD at the first valid quote after the flag (what a bot would face) ===')
    log(dist('all (broken quotes included)', sp))
    log(dist('excluding broken quotes', clean.pre_first_spread))
    log(dist('median over the 2 min window', ok.pre_median_spread))
    half = clean.pre_first_spread / 2
    log(f'\nHALF-spread = cost of crossing, per side (broken quotes excluded): median {pct(half,50):.2f}% | '
        f'mean {np.nanmean(half)*100:.2f}% | share above our 0.3% assumption {np.mean(half > 0.003):.0%} | '
        f'above 1.0%: {np.mean(half > 0.01):.0%}')
    log('\n--- by year ---')
    for y, g in clean.groupby('year'):
        log(dist(str(y), g.pre_first_spread))
    log('\n--- by flag time ---')
    for lab, lo, hi in (('7:00-8:00', 420, 480), ('8:00-9:00', 480, 540), ('9:00-9:30', 540, 570)):
        log(dist(lab, clean[(clean.flag_min >= lo) & (clean.flag_min < hi)].pre_first_spread))
    log('\n--- by price (mid) ---')
    for lab, lo, hi in (('< $2', 0, 2), ('$2-5', 2, 5), ('$5-10', 5, 10), ('> $10', 10, 1e9)):
        log(dist(lab, clean[(clean.pre_mid >= lo) & (clean.pre_mid < hi)].pre_first_spread))
    log('\n--- by news type / Ross pick ---')
    for lab, g in (('catalyst', clean[clean.type == 'catalyst']), ('no news', clean[clean.type == 'none']),
                   ("Ross's picks", clean[clean.label == 1]), ('other hits', clean[clean.label == 0])):
        log(dist(lab, g.pre_first_spread))
    if 'open_first_spread' in df:
        both = df[(df.pre_n_valid > 0) & (df.open_n_valid > 0)]
        both = both[(both.pre_first_spread <= BROKEN) & (both.open_first_spread <= BROKEN)]
        log(f'\n=== SAME stock-mornings: premarket (after flag) vs 09:45 ({len(both)} pairs) ===')
        log(dist('premarket first quote', both.pre_first_spread))
        log(dist('09:45 first quote', both.open_first_spread))
        log(f'spread at 09:45 is lower than premarket for {np.mean(both.open_first_spread < both.pre_first_spread):.0%} of pairs')
    log('\nDONE')


def main():
    summarize(collect(load_sample()))


if __name__ == '__main__':
    main()
