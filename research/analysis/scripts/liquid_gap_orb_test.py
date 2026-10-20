"""Liquid-stock news gap-up, opening-range breakout. PRE-REGISTERED in
docs/PREREG_2026_10_LIQUID_NEWS_GAP.md (committed before any data was pulled) and its addendum.
One look at the results; nothing here may change after `evaluate` has been run.

Rule (see the doc for the full text):
  universe   NYSE/Nasdaq/NYSE American common stocks (Alpaca active + inactive assets; ETFs/funds and
             non-plain tickers excluded), prior close $10-$500, prior 20-day average dollar volume >= $50M
  signal     opening gap >= 4% (open of the 09:30 bar, else 09:31, vs prior close) and a company-specific
             catalyst article between 16:00 ET the prior trading day and 09:29 ET
  entry      buy-stop at the 09:30-09:34 high + $0.01, live 09:35-10:30, fill = max(trigger bar open, level)
  exit       stop at the opening-range low - $0.01 (honest fills, checked from the bar after entry),
             otherwise the close of the 11:59 bar
  costs      0.15%/side primary, 0.30%/side robustness
Addendum (data cleaning, decided before any data was pulled): raw (unadjusted) prices are used throughout,
so a reverse split shows up as a +100% or larger "gap"; gaps above +60% are excluded as split artifacts.
Alpaca's daily open was verified to equal the 09:30 opening print, so the daily bars pre-screen gaps >= 2%
(the smallest report-only threshold) and minute bars/news are pulled only for those.

Stages (each caches and resumes):
  python research/analysis/scripts/liquid_gap_orb_test.py collect    universe, daily bars, minute bars, news
  python research/analysis/scripts/liquid_gap_orb_test.py evaluate   the one look
"""
import os
import pickle
import re
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import pytz
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import TimeFrame, _client, _fetch, _insert  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from premarket_news_test import article_type  # noqa: E402
from ross_premarket_test import DSN  # noqa: E402

from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.historical.news import NewsClient  # noqa: E402
from alpaca.data.requests import NewsRequest, StockQuotesRequest  # noqa: E402

ET = pytz.timezone('America/New_York')
CACHE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'liquid_gap'))
START, END = date(2021, 1, 4), date(2026, 10, 16)
EXCHANGES = {'NYSE', 'NASDAQ', 'AMEX'}
NAME_EXCLUDE = re.compile(r'\b(ETF|ETN|FUND|TRUST|INDEX|PROSHARES|ISHARES|SPDR|DIREXION|2X|3X|BULL|BEAR)\b', re.I)
PRICE_LO, PRICE_HI, ADV_MIN = 10, 500, 50e6
PREFILTER_GAP, GAP, GAP_CAP = 0.02, 0.04, 0.60
COST, COST_HI = 0.0015, 0.003
OPEN_MIN = 9 * 60 + 30
BOOT = 3000
RNG = np.random.default_rng(20261019)
DDL = """
CREATE TABLE IF NOT EXISTS liq_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS liq_news (
    day date, symbol varchar(10), article_id bigint, created_at timestamptz, headline text,
    n_symbols int, PRIMARY KEY (day, symbol, article_id));
CREATE TABLE IF NOT EXISTS liq_done (kind text, key text, PRIMARY KEY (kind, key));
"""


def log(*a):
    print(*a, flush=True)


def _done(conn, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT key FROM liq_done WHERE kind = %s', (kind,))
        return {r[0] for r in cur.fetchall()}


def _mark(conn, kind, key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO liq_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (kind, key))
    conn.commit()


# ── collection ────────────────────────────────────────────────────────────────

def universe():
    path = os.path.join(CACHE, 'universe.pkl')
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    from alpaca.trading.client import TradingClient
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    tc = TradingClient(os.environ['APCA_PAPER_KEY_ID'], os.environ['APCA_PAPER_SECRET_KEY'], paper=True)
    syms = set()
    for st in ('active', 'inactive'):
        # raw REST: alpaca-py's Asset model rejects exchanges it doesn't know yet (e.g. TXSE)
        for a in tc.get('/assets', {'status': st, 'asset_class': 'us_equity'}):
            sym, ex, name = a.get('symbol') or '', a.get('exchange') or '', a.get('name') or ''
            if ex in EXCHANGES and sym.isalpha() and len(sym) <= 5 and not NAME_EXCLUDE.search(name):
                syms.add(sym)
    syms = sorted(syms)
    os.makedirs(CACHE, exist_ok=True)
    pickle.dump(syms, open(path, 'wb'))
    return syms


def daily(client, syms):
    path = os.path.join(CACHE, 'daily_candidates.pkl')
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    start = ET.localize(datetime(2020, 11, 1))
    end = ET.localize(datetime(END.year, END.month, END.day, 23))
    rows, cal = [], set()
    for i in range(0, len(syms), 200):
        data = _fetch(client, syms[i:i + 200], TimeFrame.Day, start, end)
        for sym, bars in data.items():
            if len(bars) < 25:
                continue
            d = np.array([b.timestamp.astimezone(ET).date() for b in bars])
            o = np.array([b.open for b in bars], dtype=float)
            c = np.array([b.close for b in bars], dtype=float)
            v = np.array([b.volume for b in bars], dtype=float)
            cal.update(d.tolist())
            pc = np.r_[np.nan, c[:-1]]
            adv = pd.Series(np.r_[np.nan, (c * v)[:-1]]).rolling(20, min_periods=15).mean().values
            with np.errstate(invalid='ignore', divide='ignore'):
                gap = o / pc - 1
                m = (d >= START) & (d <= END) & (pc >= PRICE_LO) & (pc <= PRICE_HI) & (adv >= ADV_MIN) \
                    & (gap >= PREFILTER_GAP) & (gap <= GAP_CAP)
            for k in np.where(m)[0]:
                rows.append((sym, d[k], pc[k], o[k], gap[k], adv[k]))
        if (i // 200) % 10 == 0:
            log(f'  daily {min(i + 200, len(syms))}/{len(syms)} symbols, {len(rows)} candidate stock-days')
    cand = pd.DataFrame(rows, columns=['symbol', 'day', 'prior_close', 'open', 'gap', 'adv20'])
    out = (cand, sorted(cal))
    pickle.dump(out, open(path, 'wb'))
    return out


def minutes(conn, client, cand):
    done = _done(conn, 'minute')
    days = sorted(d for d in cand.day.unique() if d.isoformat() not in done)
    log(f'minute bars: {cand.day.nunique()} candidate days, {len(days)} to fetch')
    for i, d in enumerate(days, 1):
        syms = sorted(cand[cand.day == d].symbol)
        s = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
        e = ET.localize(datetime(d.year, d.month, d.day, 12, 0))
        for j in range(0, len(syms), 50):
            _insert(conn, 'liq_bars_1m', _fetch(client, syms[j:j + 50], TimeFrame.Minute, s, e))
        conn.commit()
        _mark(conn, 'minute', d.isoformat())
        if i % 100 == 0 or i == len(days):
            log(f'  minute {i}/{len(days)} days')


def news(conn, cand, cal):
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    nc = NewsClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])
    prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
    done = _done(conn, 'news')
    days = sorted(d for d in cand.day.unique() if d.isoformat() not in done and d in prev)
    log(f'news: {len(days)} days to fetch')
    for i, d in enumerate(days, 1):
        syms = sorted(cand[cand.day == d].symbol)
        p = prev[d]
        s = ET.localize(datetime(p.year, p.month, p.day, 16, 0))
        e = ET.localize(datetime(d.year, d.month, d.day, 9, 29, 59))
        rows = []
        for j in range(0, len(syms), 40):
            chunk = set(syms[j:j + 40])
            arts = None
            for attempt in range(6):
                try:
                    arts = nc.get_news(NewsRequest(symbols=','.join(sorted(chunk)), start=s, end=e,
                                                   limit=2000, include_content=False)).data.get('news', [])
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 ** attempt * 3)
            for a in arts or []:
                for sym in set(a.symbols or []) & chunk:
                    rows.append((d, sym, a.id, a.created_at, a.headline, len(a.symbols or [])))
            time.sleep(0.33)
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO liq_news VALUES %s ON CONFLICT DO NOTHING', rows)
        conn.commit()
        _mark(conn, 'news', d.isoformat())
        if i % 100 == 0 or i == len(days):
            log(f'  news {i}/{len(days)} days')


def collect():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    client = _client()
    syms = universe()
    log(f'universe: {len(syms)} symbols')
    cand, cal = daily(client, syms)
    log(f'daily candidates (gap 2-60%, liquid, priced $10-500): {len(cand)} stock-days over {cand.day.nunique()} days')
    minutes(conn, client, cand)
    news(conn, cand, cal)
    conn.close()
    log('DONE collect')


# ── evaluation ────────────────────────────────────────────────────────────────

def trade(a, or_n=5, last_entry=630, exit_min=719):
    m, o, h, l, c = a
    orb = np.where((m >= OPEN_MIN) & (m < OPEN_MIN + or_n))[0]
    if orb.size < 3:
        return None
    lvl, stop = h[orb].max() + 0.01, l[orb].min() - 0.01
    trig = np.where((m >= OPEN_MIN + or_n) & (m <= last_entry) & (h >= lvl))[0]
    if not trig.size:
        return {'traded': False}
    k = int(trig[0])
    entry = max(o[k], lvl)
    n, kind, fill = len(m), 'time', None
    for j in range(k + 1, n):
        if m[j] > exit_min:
            break
        if o[j] <= stop:
            kind, fill = 'gap', o[j]
            break
        if l[j] <= stop:
            kind, fill = 'stop', (min(stop, o[j + 1]) if j + 1 < n else c[j])
            break
    if fill is None:
        last = np.where(m <= exit_min)[0]
        fill = c[last[-1]]
    return {'traded': True, 'entry': entry, 'stop': stop, 'exit': fill, 'kind': kind, 'tmin': int(m[k])}


def net(t, cost):
    return t.exit * (1 - cost) / (t.entry * (1 + cost)) - 1


def net_r(t, cost):
    en = t.entry * (1 + cost)
    return (t.exit * (1 - cost) - en) / (en - t.stop)


def dci(v, days):
    s = pd.DataFrame({'v': v, 'd': days}).dropna()
    if len(s) < 10:
        return None
    g = s.groupby('d').v.agg(['sum', 'count'])
    su, n = g['sum'].values, g['count'].values
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    b = su[idx].sum(1) / n[idx].sum(1)
    return len(s), s.v.mean(), np.median(s.v), (s.v > 0).mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), len(g)


def fmt(label, s, pct=True):
    if s is None:
        return f'{label:<48} (n<10)'
    n, mean, med, pos, lo, hi, nd = s
    k, u = (100, '%') if pct else (1, 'R')
    return (f'{label:<48} n={n:>5} d={nd:>4}  mean {mean*k:+6.3f}{u}  median {med*k:+6.3f}{u}  '
            f'pos {pos:4.0%}  CI [{lo*k:+.3f}, {hi*k:+.3f}]')


def build_trades(cand, bars, cats, gap_th, need_news, **kw):
    rows = []
    for r in cand.itertuples():
        a = bars.get((r.symbol, r.day))
        if a is None:
            continue
        m, o = a[0], a[1]
        first = np.where((m == OPEN_MIN) | (m == OPEN_MIN + 1))[0]
        if not first.size:
            continue
        gap = o[first[0]] / r.prior_close - 1
        if gap < gap_th or gap > GAP_CAP:
            continue
        has_news = (r.symbol, r.day) in cats
        if need_news and not has_news:
            continue
        t = trade(a, **kw)
        if t and t['traded']:
            rows.append({'symbol': r.symbol, 'day': r.day, 'year': r.day.year, 'gap': gap, 'news': has_news, **t})
    return pd.DataFrame(rows)


def evaluate():
    cand, cal = pickle.load(open(os.path.join(CACHE, 'daily_candidates.pkl'), 'rb'))
    conn = psycopg2.connect(DSN)
    b = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et, open, high, low, close
                       FROM liq_bars_1m""", conn)
    nw = pd.read_sql('SELECT day, symbol, headline, n_symbols FROM liq_news', conn)
    conn.close()
    b['day'] = b.et.dt.date
    b['m'] = b.et.dt.hour * 60 + b.et.dt.minute
    bars = {k: (g.m.values, g.open.values, g.high.values, g.low.values, g.close.values)
            for k, g in b.sort_values(['symbol', 'et']).groupby(['symbol', 'day'])}
    nw['type'] = [article_type(h, n) for h, n in zip(nw.headline, nw.n_symbols)]
    cats = set(zip(nw[nw.type == 'catalyst'].symbol, nw[nw.type == 'catalyst'].day))
    log(f'candidate stock-days {len(cand)} | with minute bars {sum(1 for k in zip(cand.symbol, cand.day) if k in bars)} '
        f'| with a catalyst article {len(cats)}')

    T = build_trades(cand, bars, cats, GAP, True)
    log(f'\n######## PRE-REGISTERED: gap >= 4% + catalyst, 5-min ORB, stop OR low, exit 11:59 ########')
    if T.empty:
        log('no trades -> VERDICT: FAIL')
        return
    T['r'] = net(T, COST)
    T['rhi'] = net(T, COST_HI)
    T['R'] = net_r(T, COST)
    s = dci(T.r.values, T.day.values)
    log(fmt('net return @0.15%/side', s))
    log(fmt('net R @0.15%/side', dci(T.R.values, T.day.values), pct=False))
    log(fmt('net return @0.30%/side', dci(T.rhi.values, T.day.values)))
    log('exits: ' + ', '.join(f'{k} {v:.0%}' for k, v in T.kind.value_counts(normalize=True).items()))
    years = {}
    for y, g in T.groupby('year'):
        years[y] = g.r.mean()
        log(f'  {y}: trades {len(g):>4}  mean {g.r.mean()*100:+6.3f}%  pos {np.mean(g.r > 0):4.0%}')
    cut = T.r.quantile(0.99)
    trimmed = T[T.r <= cut].r.mean()
    n, mean, _, _, lo, _, _ = s
    a_, b_ = n >= 300, (mean > 0 and lo > 0)
    c_ = sum(1 for v in years.values() if v > 0) >= 4
    d_, e_ = T.rhi.mean() > 0, trimmed > 0
    log(f'\nCRITERIA (a) >=300 trades: {n} -> {"PASS" if a_ else "FAIL"}')
    log(f'         (b) mean>0, CI lower>0: {mean*100:+.3f}% / {lo*100:+.3f}% -> {"PASS" if b_ else "FAIL"}')
    log(f'         (c) positive in >=4 of 6 years: {sum(1 for v in years.values() if v > 0)} -> {"PASS" if c_ else "FAIL"}')
    log(f'         (d) still >0 at 0.30%/side: {T.rhi.mean()*100:+.3f}% -> {"PASS" if d_ else "FAIL"}')
    log(f'         (e) >0 without best 1%: {trimmed*100:+.3f}% -> {"PASS" if e_ else "FAIL"}')
    log(f'VERDICT: {"PASS" if all((a_, b_, c_, d_, e_)) else "FAIL"}')

    log('\n######## REPORT-ONLY (never used to decide), all @0.15%/side ########')
    allg = build_trades(cand, bars, cats, GAP, False)
    allg['r'] = net(allg, COST)
    log(fmt('no news requirement (all gaps >= 4%)', dci(allg.r.values, allg.day.values)))
    log(fmt('  of which news', dci(allg[allg.news].r.values, allg[allg.news].day.values)))
    log(fmt('  of which no news', dci(allg[~allg.news].r.values, allg[~allg.news].day.values)))
    diffs = [g[g.news].r.mean() - g[~g.news].r.mean() for _, g in allg.groupby('day') if g.news.any() and (~g.news).any()]
    log(fmt('  PAIRED news minus no-news, same day', dci(np.array(diffs), np.arange(len(diffs)))))
    for lab, kw in (('gap >= 2% + news', dict(gap_th=0.02)), ('gap >= 6% + news', dict(gap_th=0.06))):
        x = build_trades(cand, bars, cats, kw['gap_th'], True)
        x['r'] = net(x, COST)
        log(fmt(lab, dci(x.r.values, x.day.values)))
    x = build_trades(cand, bars, cats, GAP, True, or_n=15)
    x['r'] = net(x, COST)
    log(fmt('15-min opening range', dci(x.r.values, x.day.values)))
    x = build_trades(cand, bars, cats, GAP, True, exit_min=630)
    x['r'] = net(x, COST)
    log(fmt('time exit 10:30', dci(x.r.values, x.day.values)))

    # quoted spread at entry for a sample of primary trades
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    client = _client()
    samp = T.sample(min(200, len(T)), random_state=7)
    sp = []
    for r in samp.itertuples():
        t0 = ET.localize(datetime(r.day.year, r.day.month, r.day.day) + timedelta(minutes=r.tmin))
        try:
            q = client.get_stock_quotes(StockQuotesRequest(symbol_or_symbols=r.symbol, start=t0,
                                                           end=t0 + timedelta(minutes=1), limit=50,
                                                           feed=DataFeed.SIP)).data.get(r.symbol, [])
        except Exception:  # noqa: BLE001
            q = []
        v = [(x.ask_price - x.bid_price) / ((x.ask_price + x.bid_price) / 2) for x in q
             if x.bid_price > 0 and x.ask_price > x.bid_price]
        if v:
            sp.append(v[0])
        time.sleep(0.33)
    if sp:
        log(f'quoted spread at entry, {len(sp)} sampled trades: median {np.median(sp)*100:.3f}% '
            f'(half-spread {np.median(sp)*50:.3f}%/side), p90 {np.percentile(sp, 90)*100:.3f}%')
    T.to_csv(os.path.join(CACHE, 'trades_primary.csv'), index=False)
    log('\nDONE evaluate')


if __name__ == '__main__':
    {'collect': collect, 'evaluate': evaluate}[sys.argv[1]]()
