"""Can an LLM rate premarket catalyst headlines the way Ross Cameron judges news?

premarket_news_test.py found that movers with a real catalyst beat no-news movers (+1.0%), but
"any catalyst" is ~flat in absolute terms, while Ross's catalyst picks do far better. This tests
whether an LLM's rating of the headline separates winners from losers.

Two steps:
  export    - one row per scanner hit that has a catalyst/reaction article in the 24h before
              its flag: up to 3 most recent specific headlines, with the ticker and the leading
              company name masked (to limit the rater recalling what happened), written to
              research/analysis/outputs/llm_rating/batch_NN.csv for rater agents.
  evaluate  - read the rater outputs (score_NN.jsonl, one {"id", "score"} per line, 1-5) and
              test: forward returns by score, top-rated vs low-rated same morning (paired),
              top-rated hit per morning, and how Ross's actual picks were rated.

No parameters are fit to outcomes (the rubric is fixed in advance), so all years are scored.

Usage:
    python research/analysis/scripts/llm_catalyst_rating.py export
    python research/analysis/scripts/llm_catalyst_rating.py evaluate
"""
import glob
import json
import os
import pickle
import re
import sys

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(__file__))
from premarket_news_test import article_type  # noqa: E402
from ross_premarket_test import CACHE, DSN  # noqa: E402
from ross_pick_model_test import ci, line, log  # noqa: E402

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'llm_rating'))
BATCH = 250
HOLDS = [10, 30]
VERBS = (r'Announces?|Reports?|Receives?|Signs?|Enters?|Launch(?:es)?|To |Prices?|Granted|Secures?|'
         r'Awarded|Completes?|Provides?|Files?|Wins?|Expands?|Partners?|Achieves?|Unveils?|Submits?|'
         r'Initiates?|Regains?|Closes?|Shares|Stock|Issues?|Says|Names?|Appoints?|Posts?|Gets?|Has |'
         r'Is |Will |Joins?|Adds?|Raises?|Lands?|Doses?|Presents?|Highlights?|Confirms?|Obtains?|'
         r'Delivers?|Reaches?|Introduces?|Selected|Approved|Gains?|Teams?|Inks?|Acquires?|Agrees?|'
         r'Updates?|Begins?|Starts?|Establishes?|Demonstrates?|Showcases?|Debuts?|Reveals?|Plans?|'
         r'Expects?|Sees|Q[1-4]|FY|Fiscal|Third|Second|First|Fourth|Full')
LEAD = re.compile(rf'^(.{{2,80}}?)\s+(?=(?:{VERBS}))')
REFUSAL = 'masked'


def mask(headline, symbol):
    h = re.sub(rf'\b{re.escape(symbol)}\b', '[TICKER]', headline or '')
    h = re.sub(r'\((?:NASDAQ|NYSE|Nasdaq|NYSE American|OTC)[^)]*\)', '', h)
    m = LEAD.match(h)
    if m and not m.group(1).lower().startswith(('why', 'the ', 'fda', 'u.s.')):
        h = '[COMPANY] ' + h[m.end():]
    return re.sub(r'\s+', ' ', h).strip()


def export():
    conn = psycopg2.connect(DSN)
    news = pd.read_sql('SELECT symbol, day, created_at, headline, n_symbols FROM ross_hit_news', conn)
    conn.close()
    news['type'] = [article_type(h, n) for h, n in zip(news.headline, news.n_symbols)]
    news = news[news.type.isin(['catalyst', 'reaction'])].sort_values('created_at')
    rows = []
    for i, ((sym, day), g) in enumerate(news.groupby(['symbol', 'day'])):
        heads = [mask(h, sym) for h in g.headline.tail(3)]
        rows.append({'id': f'{sym}|{day}', 'headlines': ' || '.join(dict.fromkeys(heads))})
    df = pd.DataFrame(rows).sample(frac=1.0, random_state=7).reset_index(drop=True)  # mix years per batch
    os.makedirs(OUT, exist_ok=True)
    n = 0
    for b in range(0, len(df), BATCH):
        df.iloc[b:b + BATCH].to_csv(os.path.join(OUT, f'batch_{b // BATCH:02d}.csv'), index=False)
        n += 1
    log(f'exported {len(df)} hits with catalyst headlines into {n} batches of <= {BATCH} -> {OUT}')
    log(df.headlines.head(8).to_string())


def evaluate():
    scores = {}
    for path in sorted(glob.glob(os.path.join(OUT, 'score_*.jsonl'))):
        for ln in open(path, encoding='utf-8'):
            ln = ln.strip()
            if ln:
                try:
                    r = json.loads(ln)
                    scores[r['id']] = int(r['score'])
                except (ValueError, KeyError):
                    pass
    feats = pickle.load(open(os.path.join(CACHE, 'pick_features.pkl'), 'rb'))
    feats['id'] = feats.symbol + '|' + feats.day.astype(str)
    feats['score'] = feats.id.map(scores)
    rated = feats[feats.score.notna()]
    log(f'rated hits: {len(scores)} | joined to outcomes: {len(rated)} | '
        f'score distribution: {rated.score.value_counts().sort_index().to_dict()}')
    log(f'Ross picks among rated: {int(rated.label.sum())} | their scores: '
        f'{rated[rated.label == 1].score.value_counts().sort_index().to_dict()}')
    log(f'mean score Ross picks {rated[rated.label == 1].score.mean():.2f} vs other rated hits '
        f'{rated[rated.label == 0].score.mean():.2f}')
    unrated = feats[feats.score.isna()]
    for h in HOLDS:
        log(f'\n=== hold {h} min, bot buys the minute after the flag ===')
        for s in sorted(rated.score.unique()):
            log(line(f'LLM score {int(s)}', ci(rated[rated.score == s][f'fwd{h}'])))
        log(line('no catalyst headline (unrated)', ci(unrated[f'fwd{h}'])))
        hi, lo = rated.score >= 4, rated.score <= 2
        diffs, top1 = [], []
        for d, g in feats.groupby('day'):
            a = g[g.score >= 4][f'fwd{h}'].dropna()
            b = g[(g.score <= 2) | g.score.isna()][f'fwd{h}'].dropna()
            if len(a) and len(b):
                diffs.append(a.mean() - b.mean())
            gg = g.dropna(subset=['score', f'fwd{h}'])
            if len(gg):
                top1.append(gg.sort_values(['score', 'dv15'], ascending=False)[f'fwd{h}'].iloc[0])
        log(line('score 4-5', ci(rated[hi][f'fwd{h}'])))
        log(line('score 1-2', ci(rated[lo][f'fwd{h}'])))
        log(line('PAIRED score 4-5 minus (1-2 or no news)', ci(diffs)))
        log(line('top-rated hit per morning (tie: $ vol)', ci(top1)))
        log(line('Ross picks rated 4-5', ci(rated[hi & (rated.label == 1)][f'fwd{h}'])))
        log(line('non-Ross hits rated 4-5', ci(rated[hi & (rated.label == 0)][f'fwd{h}'])))
    rated.to_csv(os.path.join(OUT, 'rated_hits.csv'), index=False)
    log('\nDONE')


if __name__ == '__main__':
    {'export': export, 'evaluate': evaluate}[sys.argv[1]]()
