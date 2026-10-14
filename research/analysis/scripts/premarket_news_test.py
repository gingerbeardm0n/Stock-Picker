"""Do premarket movers WITH a real news catalyst beat movers without one? (no Ross involved)

ross_confirmation_news_test.py found Ross's news-driven premarket picks carry his selection
edge (+1.4% / +1.9% vs other flagged movers), his no-news picks don't. This tests the
mechanical version on EVERY hit of the hindsight-free premarket scanner.

News source: Alpaca news API (Benzinga feed), free with our key. Each hit gets every article
for its symbol published in the 24h BEFORE its flag time (no hindsight). Articles are typed
by headline, because Benzinga publishes many after-the-fact pieces:
  roundup   - "stocks moving premarket", "here are N stocks", or tagged with > 3 symbols
  reaction  - "why X shares are trading higher/lower", "shares are trading ..." (explains a
              move already under way; it still signals that a reason exists)
  catalyst  - anything else specific to the stock (<= 3 symbols): press releases, FDA,
              contracts, earnings, offerings ...
Catalyst headlines are also bucketed by keyword (fda/clinical, contract/partner, earnings,
offering/financing, other) to see which kinds carry the move.

Outcome: from pick_features.pkl -- bot buys the open of the minute after the flag, exits at
close of +10 / +30 min, 0.3% slippage each way. No model is fit, so no train/test split.
Paired test: per morning, mean of catalyst hits minus mean of no-news hits.

Articles are cached in table ross_hit_news (keeps headlines for a later LLM-rating test).

Usage:  python research/analysis/scripts/premarket_news_test.py   (local TimescaleDB up)
"""
import os
import pickle
import re
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import pytz
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE, DSN  # noqa: E402
from ross_pick_model_test import ci, line, log  # noqa: E402

from alpaca.data.historical.news import NewsClient  # noqa: E402
from alpaca.data.requests import NewsRequest  # noqa: E402

ET = pytz.timezone('America/New_York')
HOLDS = [10, 30]
DDL = """
CREATE TABLE IF NOT EXISTS ross_hit_news (
    symbol varchar(10), day date, flag_min int, article_id bigint, created_at timestamptz,
    headline text, source text, n_symbols int, PRIMARY KEY (symbol, day, article_id)
);
CREATE TABLE IF NOT EXISTS ross_hit_news_done (symbol varchar(10), day date, PRIMARY KEY (symbol, day));
"""
ROUNDUP = re.compile(r'stocks moving|here are \d+|\d+ stocks|movers|mid-day|gainers|losers|biggest|'
                     r'session|top (premarket|pre-market)|market (update|movers)|stocks to watch|'
                     r'trading higher by|trading lower by', re.I)
REACTION = re.compile(r"^why .* (shares|stock)|shares are (trading|moving|soaring|falling|up|down)|"
                      r'(shares|stock) (jump|soar|surge|spike|rise|fall|plunge|tumble)', re.I)
KINDS = [('fda/clinical', r'fda|clinical|trial|phase|approv|patent|drug|therap|data|study'),
         ('contract/partner', r'contract|agreement|partner|collaborat|order|deal|award|launch|acqui|merger'),
         ('earnings', r'earnings|revenue|results|quarter|guidance|eps|sales'),
         ('offering/financing', r'offering|priced|financing|private placement|warrant|direct|registered'),
         ]


def article_type(headline, n_symbols):
    if n_symbols > 3 or ROUNDUP.search(headline or ''):
        return 'roundup'
    if REACTION.search(headline or ''):
        return 'reaction'
    return 'catalyst'


def catalyst_kind(headline):
    for name, pat in KINDS:
        if re.search(pat, headline or '', re.I):
            return name
    return 'other'


def fetch_news(conn, hits):
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    client = NewsClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute('SELECT symbol, day FROM ross_hit_news_done')
        done = set(cur.fetchall())
    conn.commit()
    todo = [r for r in hits.itertuples() if (r.symbol, r.day) not in done]
    log(f'news: {len(hits) - len(todo)} cached, {len(todo)} to fetch')
    t0 = time.time()
    for i, r in enumerate(todo, 1):
        flag = ET.localize(datetime(r.day.year, r.day.month, r.day.day) + timedelta(minutes=int(r.flag_min)))
        for attempt in range(6):
            try:
                res = client.get_news(NewsRequest(symbols=r.symbol, start=flag - timedelta(hours=24), end=flag,
                                                  limit=50, include_content=False))
                arts = res.data.get('news', [])
                break
            except Exception as e:  # noqa: BLE001
                time.sleep(2 ** attempt * 3)
                arts = None
                if attempt == 5:
                    log(f'  GAVE UP {r.symbol} {r.day}: {str(e)[:80]}')
        if arts is None:
            continue
        rows = [(r.symbol, r.day, int(r.flag_min), a.id, a.created_at, a.headline, a.source, len(a.symbols or []))
                for a in arts]
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO ross_hit_news VALUES %s ON CONFLICT DO NOTHING', rows)
            cur.execute('INSERT INTO ross_hit_news_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (r.symbol, r.day))
        conn.commit()
        if i % 500 == 0:
            log(f'  news {i}/{len(todo)} ({time.time() - t0:.0f}s)')


def paired(df, mask_a, mask_b, h):
    diffs = []
    for d, g in df.groupby('day'):
        a, b = g[mask_a.loc[g.index]][f'fwd{h}'].dropna(), g[mask_b.loc[g.index]][f'fwd{h}'].dropna()
        if len(a) and len(b):
            diffs.append(a.mean() - b.mean())
    return ci(diffs)


def main():
    conn = psycopg2.connect(DSN)
    hits = pickle.load(open(os.path.join(CACHE, 'scanner_hits.pkl'), 'rb'))
    fetch_news(conn, hits)
    news = pd.read_sql('SELECT symbol, day, headline, n_symbols, created_at FROM ross_hit_news', conn)
    conn.close()
    news['type'] = [article_type(h, n) for h, n in zip(news.headline, news.n_symbols)]
    news['kind'] = [catalyst_kind(h) if t == 'catalyst' else None for h, t in zip(news.headline, news.type)]

    feats = pickle.load(open(os.path.join(CACHE, 'pick_features.pkl'), 'rb'))
    rank = {'catalyst': 3, 'reaction': 2, 'roundup': 1}
    best = news.assign(r=news.type.map(rank)).sort_values('r').groupby(['symbol', 'day']).tail(1)
    best_kind = (news[news.type == 'catalyst'].groupby(['symbol', 'day']).kind
                 .agg(lambda k: 'offering/financing' if 'offering/financing' in set(k) else k.iloc[-1]))
    df = feats.merge(best[['symbol', 'day', 'type']], on=['symbol', 'day'], how='left')
    df['type'] = df['type'].fillna('none')
    df = df.merge(best_kind.rename('kind').reset_index(), on=['symbol', 'day'], how='left')
    df.to_csv(os.path.join(os.path.dirname(CACHE), 'premarket_news_hits.csv'), index=False)

    log(f'\nscanner hits with outcomes: {len(df)} | best article type: {df.type.value_counts().to_dict()}')
    log('Ross picks by news type: ' + str(df[df.label == 1].type.value_counts().to_dict()))

    for h in HOLDS:
        log(f'\n=== hold {h} min, bot buys next minute after flag ===')
        for t in ('catalyst', 'reaction', 'roundup', 'none'):
            log(line(f'news type = {t}', ci(df[df.type == t][f'fwd{h}'])))
        for k in ('fda/clinical', 'contract/partner', 'earnings', 'offering/financing', 'other'):
            log(line(f'  catalyst kind = {k}', ci(df[(df.type == 'catalyst') & (df.kind == k)][f'fwd{h}'])))
        log(line('PAIRED catalyst minus no-news, same morning', paired(df, df.type == 'catalyst', df.type == 'none', h)))
        good = (df.type == 'catalyst') & (df.kind != 'offering/financing')
        log(line('PAIRED non-offering catalyst minus no-news', paired(df, good, df.type == 'none', h)))
        log(line('PAIRED any news minus no-news', paired(df, df.type != 'none', df.type == 'none', h)))
        log(line('Ross picks with catalyst', ci(df[(df.label == 1) & (df.type == 'catalyst')][f'fwd{h}'])))
        log(line('non-Ross hits with catalyst', ci(df[(df.label == 0) & (df.type == 'catalyst')][f'fwd{h}'])))
    log('\nDONE')


if __name__ == '__main__':
    main()
