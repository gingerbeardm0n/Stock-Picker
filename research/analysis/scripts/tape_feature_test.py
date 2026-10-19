"""Tape test: does order flow just before the scanner flag predict which premarket mover keeps going?

PRE-REGISTERED in docs/DECISION_2026_10_ROSS_EDGE.md sections 5, 5a and 5b (committed before any
tape feature was computed). Nothing here may be changed after seeing results.

Population: scanner hits (premarket_float_hits.csv). Decision time = the scanner flag time.
Features, from Alpaca SIP trades and quotes in the 5 minutes before the flag (exactly five):
  f_speed   log[(trades in last 2 min + 1) / (trades in the 3 min before that + 1)]
  f_buy     buy share of classified volume in the last 2 min (quote rule vs the last quote within
            60 s; between bid and ask -> tick rule; unclassifiable trades are left out)
  f_big     share of volume printed in prints >= 10,000 shares over the 5 min
  f_spread  log of the relative quoted spread at the last valid quote before the flag
  f_bid     bid size / (bid size + ask size) at that quote
Trade filter: keep only trades whose condition codes are within {' ', '@', 'T', 'F', 'I', 'E'}.
Liquidity floor: at least 20 kept trades in the 5 minutes before the flag, else excluded.
Missing any feature -> excluded, no imputation.

Outcome: entry = open of the first 1-min bar at/after the flag; exit = close of the last bar within
29 minutes of the entry bar's start (30-minute hold); cost 0.5% per side. Report-only: 10-minute hold
and 1.0% per side.

Model: logistic regression (C=0.3, balanced), walk-forward by year (train on all earlier years, a year
is scored only if >= 400 earlier complete rows exist), label = net 30-minute return > 0. Each morning
the top-scored qualified hit is traded.

PASS requires all four: (a) >= 300 out-of-sample trades; (b) mean net return > 0 with the day-clustered
95% CI lower bound > 0; (c) positive mean in at least 2 of the 3 most recent scored years; (d) mean
net return at least 0.5% above the same one-trade-per-morning rule with no tape information (the
average net return of all qualified hits that morning, i.e. the expectation of a random pick).
Any failure ends the Ross-replication line. Bar-feature pick model shown for context only.

Usage:  python research/analysis/scripts/tape_feature_test.py collect   (Alpaca, ~40-60 min, resumable)
        python research/analysis/scripts/tape_feature_test.py evaluate  (needs the local DB for outcomes)
"""
import os
import pickle
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytz
from dotenv import load_dotenv
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockQuotesRequest, StockTradesRequest

sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import CACHE  # noqa: E402
from premarket_pullback_test import load_bars, load_frame  # noqa: E402

ET = pytz.timezone('America/New_York')
ALLOWED = {' ', '@', 'T', 'F', 'I', 'E'}
BIG, LIQ_FLOOR, LIMIT, SLEEP = 10_000, 20, 200_000, 0.33
COST, MIN_TRAIN, BOOT = 0.005, 400, 3000
TAPE = ['f_speed', 'f_buy', 'f_big', 'f_spread', 'f_bid']
BAR_FEATURES = ['gap', 'pm_vol', 'rel_vol', 'price', 'flag_min', 'mom5', 'mom15', 'off_high', 'dv15', 'order']
OUT = os.path.join(CACHE, 'tape_features.csv')
RNG = np.random.default_rng(20261019)


def log(*a):
    print(*a, flush=True)


# ── collection ────────────────────────────────────────────────────────────────

def _call(fn, req):
    for attempt in range(6):
        try:
            return fn(req).data
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if 'invalid symbol' in msg or 'not found' in msg:
                return None
            time.sleep(2 ** attempt * 2)
    return None


def fetch_group(client, symbols, flag_utc):
    out = {}
    for syms in ([symbols] if len(symbols) > 1 else [symbols]):
        tr = _call(client.get_stock_trades, StockTradesRequest(
            symbol_or_symbols=syms, start=flag_utc - timedelta(minutes=5), end=flag_utc,
            limit=LIMIT, feed=DataFeed.SIP))
        time.sleep(SLEEP)
        qt = _call(client.get_stock_quotes, StockQuotesRequest(
            symbol_or_symbols=syms, start=flag_utc - timedelta(minutes=3), end=flag_utc,
            limit=LIMIT, feed=DataFeed.SIP))
        time.sleep(SLEEP)
        if tr is None or qt is None:  # one bad symbol poisons a multi-symbol call: go one by one
            for s in symbols:
                t1 = _call(client.get_stock_trades, StockTradesRequest(
                    symbol_or_symbols=s, start=flag_utc - timedelta(minutes=5), end=flag_utc,
                    limit=LIMIT, feed=DataFeed.SIP))
                time.sleep(SLEEP)
                q1 = _call(client.get_stock_quotes, StockQuotesRequest(
                    symbol_or_symbols=s, start=flag_utc - timedelta(minutes=3), end=flag_utc,
                    limit=LIMIT, feed=DataFeed.SIP))
                time.sleep(SLEEP)
                out[s] = ((t1 or {}).get(s, []), (q1 or {}).get(s, []))
        else:
            for s in symbols:
                out[s] = (tr.get(s, []), qt.get(s, []))
    return out


def tape_features(flag_utc, trades, quotes):
    kept = [x for x in trades if x.conditions is None or set(x.conditions) <= ALLOWED]
    ft = flag_utc.timestamp()
    t2 = ft - 120
    ts = np.array([x.timestamp.timestamp() for x in kept])
    px = np.array([x.price for x in kept], dtype=float)
    sz = np.array([x.size for x in kept], dtype=float)
    n5 = len(kept)
    n_recent = int((ts >= t2).sum()) if n5 else 0
    vol = sz.sum() if n5 else 0.0
    out = {'n_kept5': n5, 'trunc': len(trades) >= LIMIT, 'speed': (n_recent + 1) / (n5 - n_recent + 1),
           'big_share': float(sz[sz >= BIG].sum() / vol) if vol > 0 else 0.0,
           'buy_share': np.nan, 'spread': np.nan, 'bidratio': np.nan}
    qts = np.array([q.timestamp.timestamp() for q in quotes])
    qb = np.array([q.bid_price for q in quotes], dtype=float)
    qa = np.array([q.ask_price for q in quotes], dtype=float)
    valid = (qb > 0) & (qa > qb)
    if n5 and len(quotes):
        buy_v = sell_v = 0.0
        prev_p, prev_c = None, 0
        for k in range(n5):
            idx = int(np.searchsorted(qts, ts[k], side='right')) - 1
            c = None
            if idx >= 0 and valid[idx] and ts[k] - qts[idx] <= 60:
                if px[k] >= qa[idx]:
                    c = 1
                elif px[k] <= qb[idx]:
                    c = -1
                elif prev_p is not None:
                    c = 1 if px[k] > prev_p else (-1 if px[k] < prev_p else (prev_c or None))
            if ts[k] >= t2 and c in (1, -1):
                if c == 1:
                    buy_v += sz[k]
                else:
                    sell_v += sz[k]
            prev_p = px[k]
            if c in (1, -1):
                prev_c = c
        if buy_v + sell_v > 0:
            out['buy_share'] = buy_v / (buy_v + sell_v)
    if len(quotes) and valid.any():
        j = int(np.where(valid)[0][-1])
        q = quotes[j]
        out['spread'] = (qa[j] - qb[j]) / ((qa[j] + qb[j]) / 2)
        tot = (q.bid_size or 0) + (q.ask_size or 0)
        out['bidratio'] = q.bid_size / tot if tot > 0 else np.nan
    return out


def collect():
    frame = load_frame()
    frame = frame[frame.flag_min < 570]
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    client = StockHistoricalDataClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])
    rows, done = [], set()
    if os.path.exists(OUT):
        old = pd.read_csv(OUT, parse_dates=['day'])
        old['symbol'] = pd.read_csv(OUT, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
        old['day'] = old.day.dt.date
        rows = old.to_dict('records')
        done = set(zip(old.symbol, old.day))
    groups = [(k, g) for k, g in frame.groupby(['day', 'flag_min'])
              if any((s, k[0]) not in done for s in g.symbol)]
    log(f'stock-mornings {len(frame)} | groups (same day and flag time) to fetch {len(groups)} | cached {len(done)}')
    t0 = time.time()
    for i, ((day, fm), g) in enumerate(groups, 1):
        flag_utc = ET.localize(datetime(day.year, day.month, day.day) + timedelta(minutes=int(fm))) \
            .astimezone(pytz.utc)
        syms = [s for s in g.symbol if (s, day) not in done]
        data = fetch_group(client, syms, flag_utc)
        for s in syms:
            tr, qt = data.get(s, ([], []))
            rows.append({'symbol': s, 'day': day, 'flag_min': int(fm), **tape_features(flag_utc, tr, qt)})
        if i % 100 == 0 or i == len(groups):
            pd.DataFrame(rows).to_csv(OUT, index=False)
            log(f'  groups {i}/{len(groups)} ({time.time() - t0:.0f}s)')
    pd.DataFrame(rows).to_csv(OUT, index=False)
    log('DONE collect')


# ── evaluation ────────────────────────────────────────────────────────────────

def net_ret(entry, exitpx, cost):
    return exitpx * (1 - cost) / (entry * (1 + cost)) - 1


def outcomes(frame):
    import psycopg2
    from ross_premarket_test import DSN
    conn = psycopg2.connect(DSN)
    bars = load_bars(conn)
    conn.close()
    rows = []
    for r in frame.itertuples():
        a = bars.get((r.symbol, r.day))
        if a is None:
            continue
        m, o, h, l, c, v = a
        k = np.where(m >= r.flag_min)[0]
        if not k.size:
            continue
        e = int(k[0])
        row = {'symbol': r.symbol, 'day': r.day, 'ep': o[e]}
        for hh in (10, 30):
            ks = np.where((m >= m[e]) & (m <= m[e] + hh - 1))[0]
            row[f'x{hh}'] = c[ks[-1]]
        rows.append(row)
    return pd.DataFrame(rows)


def dci(values, days):
    s = pd.DataFrame({'v': values, 'd': days}).dropna()
    if len(s) < 10:
        return None
    g = s.groupby('d').v.agg(['sum', 'count'])
    su, n = g['sum'].values, g['count'].values
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    boots = su[idx].sum(1) / n[idx].sum(1)
    return len(s), s.v.mean(), np.percentile(boots, 2.5), np.percentile(boots, 97.5), len(g)


def walk(d, feats, cost, hold):
    d = d.copy()
    d['net'] = net_ret(d.ep.values, d[f'x{hold}'].values, cost)
    d['y'] = (d.net > 0).astype(int)
    out = []
    for y in sorted(d.year.unique()):
        tr, te = d[d.year < y], d[d.year == y]
        if len(tr) < MIN_TRAIN or te.empty or tr.y.nunique() < 2:
            continue
        sc = StandardScaler().fit(tr[feats])
        clf = LogisticRegression(C=0.3, max_iter=2000, class_weight='balanced').fit(sc.transform(tr[feats]), tr.y)
        te = te.assign(p=clf.predict_proba(sc.transform(te[feats]))[:, 1])
        te.attrs['coef'] = dict(zip(feats, clf.coef_[0]))
        out.append(te)
    if not out:
        return None, None, None
    te = pd.concat(out).reset_index(drop=True)
    top = te.loc[te.groupby('day').p.idxmax()]
    rnd = te.groupby('day').net.mean()
    return te, top, rnd


def report(label, top, rnd):
    if top is None:
        log(f'{label}: no scored years')
        return None
    m = dci(top.net.values, top.day.values)
    r = dci(rnd.values, rnd.index.values)
    n, mean, lo, hi, nd = m
    log(f'{label:<46} trades {n:>4} | model mean {mean*100:+6.2f}%  CI [{lo*100:+.2f}, {hi*100:+.2f}] | '
        f'random-pick mean {r[1]*100:+6.2f}% | model minus random {(mean - r[1])*100:+.2f}%')
    return n, mean, lo, r[1]


def evaluate():
    frame = load_frame()
    tape = pd.read_csv(OUT, parse_dates=['day'])
    tape['symbol'] = pd.read_csv(OUT, usecols=['symbol'], dtype=str, keep_default_na=False).symbol
    tape['day'] = tape.day.dt.date
    out = outcomes(frame)
    df = frame.merge(tape, on=['symbol', 'day'], how='inner', suffixes=('', '_t')).merge(out, on=['symbol', 'day'])
    feats = pickle.load(open(os.path.join(CACHE, 'pick_features.pkl'), 'rb'))
    feats['day'] = pd.to_datetime(feats.day).dt.date
    df = df.merge(feats[['symbol', 'day'] + BAR_FEATURES].drop_duplicates(['symbol', 'day']),
                  on=['symbol', 'day'], how='left', suffixes=('', '_b'))
    df['f_speed'], df['f_buy'], df['f_big'] = np.log(df.speed), df.buy_share, df.big_share
    df['f_spread'], df['f_bid'] = np.log(df.spread), df.bidratio
    n0 = len(df)
    illiquid = df.n_kept5 < LIQ_FLOOR
    missing = df[TAPE].isna().any(axis=1) | df.x30.isna()
    d = df[~illiquid & ~missing].copy()
    log(f'stock-mornings with tape rows: {n0} | below liquidity floor: {int(illiquid.sum())} | '
        f'missing feature or outcome: {int((~illiquid & missing).sum())} | qualified: {len(d)} '
        f'({d.day.nunique()} days) | truncated pulls: {int(df.trunc.sum())}')

    log('\n######## PRE-REGISTERED TEST: tape model, 30-min hold, 0.5%/side ########')
    te, top, rnd = walk(d, TAPE, COST, 30)
    res = report('tape model', top, rnd)
    if res is None:
        log('VERDICT: FAIL (no scored year with enough training data)')
        return
    n, mean, lo, rmean = res
    years = sorted(top.year.unique())
    log('per year (top pick each morning):')
    peryear = {}
    for y in years:
        t = top[top.year == y]
        peryear[y] = t.net.mean()
        r = rnd[[x for x in rnd.index if x in set(t.day)]].mean()
        log(f'  {y}: trades {len(t):>3}  mean {t.net.mean()*100:+6.2f}%  pos {np.mean(t.net > 0):4.0%}  '
            f'random-pick {r*100:+6.2f}%')
    recent = years[-3:]
    pos_recent = sum(1 for y in recent if peryear[y] > 0)
    a, b = n >= 300, (mean > 0 and lo > 0)
    c_, d_ = pos_recent >= 2, (mean - rmean) >= 0.005
    log(f'\nCRITERIA  (a) >=300 trades: {n} -> {"PASS" if a else "FAIL"}')
    log(f'          (b) mean>0 and CI lower>0: {mean*100:+.2f}% / {lo*100:+.2f}% -> {"PASS" if b else "FAIL"}')
    log(f'          (c) positive in >=2 of last 3 scored years {recent}: {pos_recent} -> {"PASS" if c_ else "FAIL"}')
    log(f'          (d) beats random pick by >=0.5%: {(mean - rmean)*100:+.2f}% -> {"PASS" if d_ else "FAIL"}')
    log(f'VERDICT: {"PASS" if (a and b and c_ and d_) else "FAIL"}')
    coefs = te[te.year == years[-1]].attrs.get('coef') or {}
    if coefs:
        log('latest model weights (standardized): ' + ', '.join(f'{k} {v:+.2f}' for k, v in coefs.items()))
    log(f'top picks that were Ross picks: {top.label.mean():.1%} (vs {te.label.mean():.1%} of all qualified hits)')

    log('\n######## REPORT-ONLY (never used to decide) ########')
    for lab, cost, hold in (('10-min hold, 0.5%/side', COST, 10), ('30-min hold, 1.0%/side', 0.01, 30)):
        _, t2, r2 = walk(d, TAPE, cost, hold)
        report(lab, t2, r2)
    db = d.dropna(subset=BAR_FEATURES)
    _, t3, r3 = walk(db, BAR_FEATURES, COST, 30)
    report('bar-feature pick model (context), 30-min, 0.5%', t3, r3)
    log('\nDONE evaluate')


if __name__ == '__main__':
    {'collect': collect, 'evaluate': evaluate}[sys.argv[1]]()
