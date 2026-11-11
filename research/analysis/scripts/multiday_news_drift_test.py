"""Multi-day drift after news gap-ups (enter at the gap-day close, hold days). PRE-REGISTERED in
docs/PREREG_2026_11_MULTIDAY_NEWS_DRIFT.md (rule + addendum committed before this script existed and before any
outcome data was pulled). One look at the results; nothing here may change after `evaluate` has been run.

Rule (see the doc for the full text):
  universe   US common stocks (liquid_gap_orb_test universe cache), raw prior close $2-$500,
             raw 20-day average dollar volume (prior days) >= $5M
  event      split-adjusted open of D >= +5% (and <= +300%) vs prior close, and >= 1 `catalyst` article created
             16:00 ET prior trading day .. 09:29:59 ET on D (news reused from the intraday test's ind_news table)
  trade      long at the close of D, exit at the close of D+5 (last close if the stock stops trading first);
             one open position per symbol; costs 0.25%/side (0.50% robustness)
  stats      mean net per trade, bootstrap CI resampling calendar months; also net minus SPY over the same days

Stages:
  python research/analysis/scripts/multiday_news_drift_test.py collect    daily bars (raw + split-adjusted), cached
  python research/analysis/scripts/multiday_news_drift_test.py check      counts / coverage only, NO returns
  python research/analysis/scripts/multiday_news_drift_test.py evaluate   the one sealed look
  python research/analysis/scripts/multiday_news_drift_test.py selftest   synthetic unit tests (no DB/network)
"""
import argparse
import glob
import os
import pickle
import sys
import time
import warnings
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, _client  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
import liquid_gap_orb_test as lg  # noqa: E402  (universe cache, dci bootstrap, fmt, DSN)
from premarket_news_test import article_type  # noqa: E402

from alpaca.data.enums import Adjustment, DataFeed  # noqa: E402
from alpaca.data.requests import StockBarsRequest  # noqa: E402
from alpaca.data.timeframe import TimeFrame  # noqa: E402

warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'multiday_news'))
# research/analysis/outputs/ is gitignored
START, END = date(2016, 1, 4), date(2026, 10, 23)
FETCH_START, FETCH_END = date(2015, 11, 1), date(2026, 11, 10)
SCREEN_PC_LO, SCREEN_PC_HI, SCREEN_ADV = 1, 500, 2e6      # superset screen (= ind_news coverage)
PC_LO, PC_HI, ADV_MIN = 2, 500, 5e6                       # primary tier
LIQ = (10, 500, 50e6)
ROSS = (1, 20, 2e6)
GAP, GAP_CAP = 0.05, 3.0
HOLDS = (1, 5, 20)
HOLD = 5
COST, COST_HI = 0.0025, 0.005
DELIST_DAYS = 7
BATCH = 200
MIN_TRADES, MIN_YEARS_POS = 1000, 6
HALVES = ((2016, 2020), (2021, 2026))
lg.RNG = np.random.default_rng(20261111)

_BUF = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    _BUF.append(s)
    print(s, flush=True)


# ── collection ───────────────────────────────────────────────────────────────

def fetch(client, syms, adj):
    s = ET.localize(datetime.combine(FETCH_START, datetime.min.time()))
    e = ET.localize(datetime(FETCH_END.year, FETCH_END.month, FETCH_END.day, 23))
    for attempt in range(6):
        try:
            req = StockBarsRequest(symbol_or_symbols=syms, timeframe=TimeFrame.Day, start=s, end=e,
                                   feed=DataFeed.SIP, adjustment=adj)
            return client.get_stock_bars(req).data
        except Exception as ex:  # noqa: BLE001
            msg = str(ex)
            if 'invalid symbol' in msg.lower() and len(syms) > 1:
                mid = len(syms) // 2
                out = dict(fetch(client, syms[:mid], adj) or {})
                out.update(fetch(client, syms[mid:], adj) or {})
                return out
            if attempt == 5:
                log(f'  fetch GAVE UP ({len(syms)} syms, {adj}): {msg[:100]}')
                return None
            time.sleep(2 ** attempt * (5 if '429' in msg else 1))


def screen(sym, d, ro, rc, rv, ao, ac, last_global):
    """Candidate rows for one symbol. d: ascending dates; r*: raw open/close/volume; a*: split-adjusted open/close
    (same dates). Universe filters use only bars strictly before day k (look-ahead guard)."""
    n = len(d)
    if n < 16:
        return []
    pc = np.r_[np.nan, rc[:-1]]
    adv = pd.Series(np.r_[np.nan, (rc * rv)[:-1]]).rolling(20, min_periods=15).mean().values
    with np.errstate(invalid='ignore', divide='ignore'):
        gap = ao / np.r_[np.nan, ac[:-1]] - 1
        m = (d >= START) & (d <= END) & (pc >= SCREEN_PC_LO) & (pc <= SCREEN_PC_HI) & (adv >= SCREEN_ADV) \
            & (np.abs(gap) >= GAP) & (gap <= GAP_CAP)
    delisted = d[-1] < last_global - timedelta(days=DELIST_DAYS)
    rows = []
    for k in np.where(m)[0]:
        r = dict(symbol=sym, day=d[k], k=int(k), prev_day=d[k - 1], pc=float(pc[k]), adv=float(adv[k]),
                 gap=float(gap[k]), entry=float(ac[k]),
                 open1=float(ao[k + 1]) if k + 1 < n else np.nan,
                 open1_day=d[k + 1] if k + 1 < n else None)
        for h in HOLDS:
            if k + h < n:
                r[f'x{h}'], r[f'xd{h}'] = float(ac[k + h]), d[k + h]
            elif delisted:
                r[f'x{h}'], r[f'xd{h}'] = float(ac[-1]), d[-1]
            else:
                r[f'x{h}'], r[f'xd{h}'] = np.nan, None
        rows.append(r)
    return rows


def _arrays(bars):
    d = np.array([b.timestamp.astimezone(ET).date() for b in bars])
    return d, np.array([b.open for b in bars], float), np.array([b.close for b in bars], float), \
        np.array([b.volume for b in bars], float)


def collect(_args):
    os.makedirs(OUT, exist_ok=True)
    client = _client()
    spy_path = os.path.join(OUT, 'spy.pkl')
    if not os.path.exists(spy_path):
        b = fetch(client, ['SPY'], Adjustment.ALL)['SPY']
        d, _, c, _ = _arrays(b)
        pickle.dump(dict(zip(d, c)), open(spy_path, 'wb'))
    spy = pickle.load(open(spy_path, 'rb'))
    last_global = max(spy)
    log(f'SPY bars: {len(spy)} days, last {last_global}')
    if not os.path.exists(os.path.join(lg.CACHE, 'universe.pkl')):
        raise SystemExit('universe cache missing; refusing to call the trading API')
    syms = lg.universe()
    nb = -(-len(syms) // BATCH)
    log(f'universe {len(syms)} symbols, {nb} batches')
    pending, t0 = [], time.time()
    for bi in range(nb):
        path = os.path.join(OUT, f'cand_{bi:03d}.pkl')
        if os.path.exists(path):
            continue
        chunk = syms[bi * BATCH:(bi + 1) * BATCH]
        raw, adj = fetch(client, chunk, Adjustment.RAW), fetch(client, chunk, Adjustment.SPLIT)
        if raw is None or adj is None:
            pending.append(bi)
            continue
        rows, mism = [], 0
        for sym, rb in raw.items():
            ab = adj.get(sym)
            if not ab:
                continue
            d, ro, rc, rv = _arrays(rb)
            da, ao, ac, _ = _arrays(ab)
            if len(d) != len(da) or (d != da).any():
                common = np.intersect1d(d, da)
                ir, ia = np.isin(d, common), np.isin(da, common)
                d, ro, rc, rv, ao, ac = d[ir], ro[ir], rc[ir], rv[ir], ao[ia], ac[ia]
                mism += 1
            rows += screen(sym, d, ro, rc, rv, ao, ac, last_global)
        pickle.dump(rows, open(path, 'wb'))
        log(f'  batch {bi + 1}/{nb}: {len(raw)} symbols, {len(rows)} candidates, {mism} date mismatches '
            f'({time.time() - t0:.0f}s)')
    if pending:
        log(f'PENDING batches: {pending} -- rerun collect')
        sys.exit(2)
    log('DONE collect')


# ── evaluation helpers ───────────────────────────────────────────────────────

def load_cand():
    files = sorted(glob.glob(os.path.join(OUT, 'cand_*.pkl')))
    rows = [r for f in files for r in pickle.load(open(f, 'rb'))]
    return pd.DataFrame(rows), len(files)


def load_news_flags(conn):
    """(day, symbol) -> (has_catalyst, has_any) for articles created before 09:30:00 ET on day."""
    q = """SELECT day, symbol, headline, n_symbols FROM ind_news
           WHERE created_at < ((day + time '09:30') AT TIME ZONE 'America/New_York')"""
    nw = pd.read_sql(q, conn)
    nw['cat'] = [article_type(h or '', n) == 'catalyst' for h, n in zip(nw.headline, nw.n_symbols)]
    g = nw.groupby(['day', 'symbol']).cat.agg(['any', 'size']).reset_index()
    return g.rename(columns={'any': 'has_cat', 'size': 'n_art'})


def news_days_done(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT key FROM ind_done WHERE kind = 'news'")
        return {date.fromisoformat(r[0]) for r in cur.fetchall()}


def attach_news(c, flags):
    c = c.merge(flags, on=['day', 'symbol'], how='left')
    c['has_cat'] = c.has_cat.fillna(False).astype(bool)
    c['n_art'] = c.n_art.fillna(0).astype(int)
    return c


def tier_mask(c, lo, hi, adv):
    return (c.pc >= lo) & (c.pc <= hi) & (c.adv >= adv)


def dedupe(c, hold):
    """One open position per symbol: skip event at index k if a kept trade entered at j has k <= j + hold."""
    keep = np.zeros(len(c), bool)
    c = c.sort_values(['symbol', 'k'])
    last = {}
    for i, (s, k) in enumerate(zip(c.symbol.values, c.k.values)):
        j = last.get(s)
        if j is None or k > j + hold:
            keep[i] = True
            last[s] = k
    return c[keep]


def net(ret, cost):
    return (1 + ret) * (1 - cost) / (1 + cost) - 1


def spy_ret(spy, d0, d1):
    a, b = spy.get(d0), spy.get(d1)
    return b / a - 1 if a and b else np.nan


def trades(c, spy, hold, side=1, cost=COST, entry='close'):
    """Trade frame for already-selected events. side=+1 long, -1 short."""
    c = dedupe(c, hold)
    if entry == 'close':
        e, d0 = c.entry, c.day
    else:
        e, d0 = c.open1, c.open1_day
    x, d1 = c[f'x{hold}'], c[f'xd{hold}']
    ok = x.notna() & e.notna() & d1.notna()
    if entry != 'close':
        ok &= c.open1_day.notna() & (pd.Series([a is not None and b is not None and b > a
                                                for a, b in zip(c.open1_day, d1)], index=c.index))
    c, e, d0, x, d1 = c[ok], e[ok], d0[ok], x[ok], d1[ok]
    gross = side * (x / e - 1)
    t = pd.DataFrame({'symbol': c.symbol, 'day': c.day, 'gross': gross})
    t['r'] = net(gross, cost)
    sp = np.array([spy_ret(spy, a, b) for a, b in zip(d0, d1)])
    t['mkt'] = t.r - side * sp
    t['month'] = [d.strftime('%Y-%m') for d in t.day]
    t['year'] = [d.year for d in t.day]
    return t


def summ(label, t, col='r'):
    return lg.fmt(label, lg.dci(t[col].values, t.month.values) if len(t) else None)


# ── stages ───────────────────────────────────────────────────────────────────

def check(_args):
    c, nf = load_cand()
    conn = psycopg2.connect(lg.DSN)
    done = news_days_done(conn)
    flags = load_news_flags(conn)
    conn.close()
    c = attach_news(c, flags)
    p = c[tier_mask(c, PC_LO, PC_HI, ADV_MIN)]
    up = p[p.gap >= GAP]
    log(f'candidate batches {nf}; candidate rows {len(c):,} over {c.day.nunique()} days '
        f'({c.day.min()}..{c.day.max()})')
    missing = sorted(set(c.day) - done)
    log(f'candidate days with no completed news fetch: {len(missing)} {missing[:10]}')
    log(f'primary-tier gap-ups >= 5%: {len(up):,}; with catalyst news {int(up.has_cat.sum()):,}; '
        f'no article at all {int((up.n_art == 0).sum()):,}')
    ev = up[up.has_cat]
    log('primary events per year: ' + ', '.join(f'{y}:{n}' for y, n in
                                                 ev.groupby([d.year for d in ev.day]).size().items()))
    log(f'primary events missing a 5-day exit: {int(ev.x5.isna().sum())}; exits by last close '
        f'(stopped trading): {int(sum(1 for a, b in zip(ev.xd5, ev.day) if a is not None and (a - b).days < 5))}')
    log('NO RETURNS PRINTED (check only)')


def primary_block(T):
    log('######## PRE-REGISTERED: primary tier ($2-$500, ADV >= $5M), gap >= 5% on catalyst news, '
        'long at close of D, exit close D+5 ########')
    r = T['primary']
    s = lg.dci(r.r.values, r.month.values)
    sm = lg.dci(r.mkt.values, r.month.values)
    log(summ('net @0.25%/side (primary)', r))
    log(summ('market-adjusted net @0.25%/side', r, 'mkt'))
    hi = T['primary_hi']
    log(summ('net @0.50%/side', hi))
    log(f'gross mean (no costs): {r.gross.mean() * 100:+.3f}%')
    years = sorted(r.year.unique())
    ym = r.groupby('year').r.agg(['size', 'mean', lambda v: (v > 0).mean()])
    for y, row in ym.iterrows():
        log(f'  {y}: trades {int(row.iloc[0]):>5}  mean {row.iloc[1] * 100:+.3f}%  pos {row.iloc[2]:.0%}')
    halves = [r[(r.year >= a) & (r.year <= b)].r.mean() for a, b in HALVES]
    npos = int((ym['mean'] > 0).sum())
    trim = r[r.r <= np.percentile(r.r, 99)].r.mean()
    crit = [
        ('(a) >= 1000 trades', f'{len(r)}', len(r) >= MIN_TRADES),
        ('(b) mean > 0 and CI lower > 0', f'{s[1] * 100:+.3f}% / {s[4] * 100:+.3f}%', s[1] > 0 and s[4] > 0),
        ('(c) market-adjusted mean > 0 and CI lower > 0', f'{sm[1] * 100:+.3f}% / {sm[4] * 100:+.3f}%',
         sm[1] > 0 and sm[4] > 0),
        ('(d) mean > 0 in 2016-2020 and 2021-2026', f'{halves[0] * 100:+.3f}% / {halves[1] * 100:+.3f}%',
         all(h > 0 for h in halves)),
        (f'(e) positive mean in >= {MIN_YEARS_POS} of {len(years)} years', f'{npos}', npos >= MIN_YEARS_POS),
        ('(f) mean > 0 at 0.50%/side', f'{hi.r.mean() * 100:+.3f}%', hi.r.mean() > 0),
        ('(g) mean > 0 after dropping best 1%', f'{trim * 100:+.3f}%', trim > 0),
    ]
    log('')
    for name, val, ok in crit:
        log(f'CRITERIA {name}: {val} -> {"PASS" if ok else "FAIL"}')
    log(f'VERDICT: {"PASS" if all(c[2] for c in crit) else "FAIL"}')


def evaluate(_args):
    c, nf = load_cand()
    spy = pickle.load(open(os.path.join(OUT, 'spy.pkl'), 'rb'))
    conn = psycopg2.connect(lg.DSN)
    done = news_days_done(conn)
    c = attach_news(c, load_news_flags(conn))
    conn.close()
    missing = set(c.day) - done
    if missing:
        raise SystemExit(f'{len(missing)} candidate days lack a completed news fetch; run check')
    log(f'SEALED {START}..{END} | candidate rows {len(c):,} | batches {nf}')
    P = c[tier_mask(c, PC_LO, PC_HI, ADV_MIN)]
    up, dn = P[P.gap >= GAP], P[P.gap <= -GAP]
    T = {'primary': trades(up[up.has_cat], spy, HOLD),
         'primary_hi': trades(up[up.has_cat], spy, HOLD, cost=COST_HI)}
    primary_block(T)

    log('')
    log('######## REPORT-ONLY (never used to decide), @0.25%/side ########')
    ev = up[up.has_cat]
    log('-- holds')
    for h in HOLDS:
        log(summ(f'hold {h} day(s)', trades(ev, spy, h)))
        log(summ(f'hold {h} day(s), market-adjusted', trades(ev, spy, h), 'mkt'))
    log('-- news vs no-news (gap >= 5%, hold 5)')
    nn = trades(up[up.n_art == 0], spy, HOLD)
    log(summ('no-news gap-ups, long', nn))
    log(summ('no-news gap-ups, long, market-adjusted', nn, 'mkt'))
    log(f'  news minus no-news (mean net): {(T["primary"].r.mean() - nn.r.mean()) * 100:+.3f}%')
    log(summ('no-news gap-ups, SHORT', trades(up[up.n_art == 0], spy, HOLD, side=-1)))
    log(summ('catalyst gap-downs <= -5%, SHORT', trades(dn[dn.has_cat], spy, HOLD, side=-1)))
    log('-- gap thresholds (catalyst, hold 5)')
    for g in (0.10, 0.20):
        log(summ(f'gap >= {g:.0%}', trades(up[up.has_cat & (up.gap >= g)], spy, HOLD)))
    log('-- tiers (catalyst gap-ups >= 5%, hold 5)')
    for name, (lo, hi, adv) in (('liquid $10-$500, ADV >= $50M', LIQ), ('Ross-style $1-$20, ADV >= $2M', ROSS)):
        x = c[tier_mask(c, lo, hi, adv) & (c.gap >= GAP) & c.has_cat]
        log(summ(name, trades(x, spy, HOLD)))
    log('-- entry at open of D+1 (exit close D+5)')
    log(summ('open D+1 entry', trades(ev, spy, HOLD, entry='open1')))
    r = T['primary']
    log('-- primary distribution')
    log(f'  median {r.r.median() * 100:+.3f}%  pos {(r.r > 0).mean():.0%}  p1 {np.percentile(r.r, 1) * 100:+.2f}%  '
        f'p99 {np.percentile(r.r, 99) * 100:+.2f}%')
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'evaluate_{datetime.now():%Y%m%d_%H%M%S}.txt')
    open(path, 'w', encoding='utf-8').write('\n'.join(_BUF))
    r.to_csv(os.path.join(OUT, 'trades_primary.csv'), index=False)
    log(f'DONE evaluate (output saved to {path})')


# ── selftest ─────────────────────────────────────────────────────────────────

def selftest(_args):
    fails = 0

    def ok(cond, name):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name)
        fails += 0 if cond else 1

    d = np.array([date(2016, 1, 4) + timedelta(days=i) for i in range(40)])
    rc = np.full(40, 10.0)
    rv = np.full(40, 1e6)                 # $10M/day
    ao, ac = rc.copy(), rc.copy()
    ao[25], ac[25] = 11.0, 12.0           # +10% gap on day 25
    rv[25] = 1e9                          # huge volume ON the gap day must not enter its own ADV
    rows = screen('T', d, ao.copy(), rc, rv, ao, ac, last_global=d[-1])
    ok(len(rows) == 2 and rows[0]['k'] == 25, 'gap detected at k=25 (and the -17% day after as gap-down)')
    r = rows[0]
    ok(abs(r['adv'] - 1e7) < 1, 'ADV uses prior days only')
    ok(abs(r['gap'] - 0.10) < 1e-9 and r['entry'] == 12.0, 'gap/entry from adjusted bars')
    ok(r['x5'] == ac[30] and r['xd5'] == d[30], '5-day exit = close of k+5')
    rows2 = screen('T', d[:28], ao[:28], rc[:28], rv[:28], ao[:28], ac[:28], last_global=d[-1])
    ok(rows2[0]['x5'] == ac[27] and rows2[0]['xd5'] == d[27], 'delisted -> exit at last close')
    rows3 = screen('T', d[:28], ao[:28], rc[:28], rv[:28], ao[:28], ac[:28], last_global=d[27])
    ok(np.isnan(rows3[0]['x5']), 'data end (not delisted) -> no exit')
    cc = pd.DataFrame({'symbol': ['A'] * 4 + ['B'], 'k': [10, 14, 15, 21, 12]})
    ok(list(dedupe(cc, 5).k) == [10, 21, 12] or sorted(dedupe(cc, 5).k) == [10, 12, 21], 'overlap dedupe')
    ok(abs(net(0.0, 0.0025) - (0.9975 / 1.0025 - 1)) < 1e-12, 'net cost formula')
    print(f'{fails} failures')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('stage', choices=['collect', 'check', 'evaluate', 'selftest'])
    a = ap.parse_args()
    {'collect': collect, 'check': check, 'evaluate': evaluate, 'selftest': selftest}[a.stage](a)
