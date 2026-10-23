"""Fade liquid gap-ups that have NO news, on fresh years 2016-2020. PRE-REGISTERED in
docs/PREREG_2026_10_NO_NEWS_GAP_FADE.md (committed before any 2016-2020 data was pulled).
One look at the sealed result; nothing here may change after `evaluate` has been run on 2016-2020.

Rule (see the doc for the full text; this file implements it literally):
  universe   same US common-stock list as liquid_gap_orb_test.universe() (Alpaca active + inactive assets,
             NYSE/Nasdaq/NYSE American, plain tickers, ETFs/funds excluded)
  screen     prior close $10-$500; prior-20-trading-day average dollar volume (close x volume, prior days
             only) >= $50M; gap = official daily open / prior close - 1 in [+4%, +60%]
  no news    no article typed `catalyst` by premarket_news_test.article_type (unchanged), Alpaca/Benzinga news
             tagged to the symbol, created 16:00 ET the prior trading day .. 09:29:59 ET
  trade      SHORT at the open of the first one-minute bar 09:31-09:35 (none: no trade); cover at the close of
             the last one-minute bar <= 11:59 (must be a later bar than the entry bar); no stop; every
             qualifying stock-day trades
  return     -(cover / entry - 1) - 2 x cost; cost 0.15%/side primary, 0.30%/side robustness; borrow free
  period     2016-01-04 .. 2020-12-31 decides. CIs: day-clustered bootstrap (liquid_gap_orb_test.dci)
  pass bar   (a) >= 1,000 trades (b) mean > 0 @0.15% and day-clustered 95% CI lower bound > 0
             (c) positive mean in >= 4 of the 5 years (d) mean > 0 @0.30% (e) mean > 0 after dropping the
             best 1% of trades

Ambiguities resolved (closest to liquid_gap_orb_test.py unless the prereg is explicit):
  * ADV uses the symbol's own prior 20 daily bars with min_periods=15 (as the reference does).
  * "prior close" = close of the symbol's previous daily bar; its date is stored (prev_day) and the number of
    candidates whose previous bar is not the previous market day is reported by `check`.
  * Cost is applied as the prereg text says: gross short return minus 2 x per-side cost.
  * The 5% stop (report-only) uses the reference's honest-fill convention mirrored for a short: a bar that
    OPENS at/through the stop fills at its open; an intrabar touch fills at max(stop, next bar open). It is
    checked from the entry bar itself (entry is at that bar's open, so its high already counts).
  * Alpaca's SIP history starts 2016-01-04 (verified: daily and minute). A stock-day needs >= 15 prior daily
    bars for the 20-day ADV, so the first candidates are 2016-01-26; 2016-01-04..2016-01-25 cannot qualify
    (about 15 of ~1,260 market days). Nothing is imputed.
  * Gap for the decision comes from the daily bar's open (the prereg's "official open"), not the 09:30 bar.

Stages (each caches in the DB and resumes; tables prefixed fade_):
  python research/analysis/scripts/no_news_gap_fade_test.py collect [--start 2016-01-04 --end 2020-12-31]
        [--accept-empty]     daily bars -> candidates -> news -> 1-min bars 09:30-15:59 for ALL candidates
  python research/analysis/scripts/no_news_gap_fade_test.py check [--start .. --end ..]
        counts / coverage / look-ahead / data-quality checks only. Prints NO returns.
  python research/analysis/scripts/no_news_gap_fade_test.py evaluate            the sealed 2016-2020 look
  python research/analysis/scripts/no_news_gap_fade_test.py evaluate --insample same code on 2021-2026
        (liq_* tables: report-only context; bars end at 11:59/12:00 so the 15:59 variant is skipped)
A unit of work whose fetch gave up (`_fetch` returns {}) is NOT marked done; collect exits with code 2 and lists
what is pending. Re-run collect to retry. --accept-empty marks currently-empty units done (use only after a
retry confirmed they are genuinely empty).
"""
import argparse
import os
import pickle
import sys
import time
import warnings
from collections import Counter
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, TimeFrame, _client, _fetch, _insert  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
import liquid_gap_orb_test as lg  # noqa: E402  (universe cache, dci bootstrap, fmt, article_type, DSN)
from premarket_news_test import article_type  # noqa: E402

from alpaca.data.historical.news import NewsClient  # noqa: E402
from alpaca.data.requests import NewsRequest  # noqa: E402

warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')

DSN = lg.DSN
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'no_news_fade'))
SEAL_START, SEAL_END = date(2016, 1, 4), date(2020, 12, 31)
IN_START, IN_END = date(2021, 1, 4), date(2026, 10, 16)
PRICE_LO, PRICE_HI, ADV_MIN = 10, 500, 50e6
GAP_LO, GAP_HI = 0.04, 0.60
COST, COST_HI = 0.0015, 0.003
ENTRY_FIRST, ENTRY_LAST = 9 * 60 + 31, 9 * 60 + 35
COVER_1159, COVER_1030, COVER_1559 = 11 * 60 + 59, 10 * 60 + 30, 15 * 60 + 59
STOP_PCT = 0.05
HISTORY_DAYS = 50        # calendar days of daily bars fetched before --start (>= 20 trading days + 1)
BATCH_DAILY, BATCH_MIN, BATCH_NEWS = 200, 50, 40
NEWS_LIMIT = 2000
CAL_MIN_SYMS = 20        # a weekday counts as a market day when >= this many symbols have a daily bar
BOOT_SEED = 20261023
MIN_TRADES, MIN_YEARS_POS = 1000, 4

DDL = """
CREATE TABLE IF NOT EXISTS fade_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS fade_news (
    day date, symbol varchar(10), article_id bigint, created_at timestamptz, headline text,
    n_symbols int, PRIMARY KEY (day, symbol, article_id));
CREATE TABLE IF NOT EXISTS fade_cand (
    symbol varchar(10), day date, prior_close double precision, open double precision,
    gap double precision, adv20 double precision, prev_day date, PRIMARY KEY (symbol, day));
CREATE TABLE IF NOT EXISTS fade_cal (day date PRIMARY KEY, n int);
CREATE TABLE IF NOT EXISTS fade_done (kind text, key text, PRIMARY KEY (kind, key));
"""

_BUF = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    _BUF.append(s)
    print(s, flush=True)


# ── resume markers (parameterized copies of liquid_gap_orb_test._done/_mark, which hardcode liq_done) ─────────

def _done(conn, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT key FROM fade_done WHERE kind = %s', (kind,))
        return {r[0] for r in cur.fetchall()}


def _mark(conn, kind, key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO fade_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (kind, key))
    conn.commit()


def get_universe():
    # liquid_gap_orb_test.universe() would call Alpaca's trading API (asset list) if its cache were missing.
    # This experiment must only touch market-data endpoints, so insist on the cached list.
    if not os.path.exists(os.path.join(lg.CACHE, 'universe.pkl')):
        raise SystemExit(f'universe cache missing at {lg.CACHE}\\universe.pkl; refusing to call the trading API')
    return lg.universe()


# ── collection ────────────────────────────────────────────────────────────────

def screen_daily(d, o, c, v, start, end):
    """Candidate rows for one symbol from its ascending daily bars (d: dates, o/c/v: float arrays).
    Look-ahead guard: prior close and the 20-day dollar-volume average use bars strictly BEFORE day k."""
    if len(d) < 16:          # need >= 15 prior bars for the average (min_periods=15) plus the day itself
        return []
    pc = np.r_[np.nan, c[:-1]]
    pday = np.concatenate([np.array([None], dtype=object), d[:-1]])
    adv = pd.Series(np.r_[np.nan, (c * v)[:-1]]).rolling(20, min_periods=15).mean().values
    with np.errstate(invalid='ignore', divide='ignore'):
        gap = o / pc - 1
        m = (d >= start) & (d <= end) & (pc >= PRICE_LO) & (pc <= PRICE_HI) & (adv >= ADV_MIN) \
            & (gap >= GAP_LO) & (gap <= GAP_HI)
    return [(d[k], float(pc[k]), float(o[k]), float(gap[k]), float(adv[k]), pday[k]) for k in np.where(m)[0]]


def stage_daily(conn, client, syms, start, end, accept_empty=False):
    fs = ET.localize(datetime.combine(start - timedelta(days=HISTORY_DAYS), datetime.min.time()))
    fe = ET.localize(datetime(end.year, end.month, end.day, 23))
    done = _done(conn, 'daily')
    nb = -(-len(syms) // BATCH_DAILY)
    pending, t0, n_new = [], time.time(), 0
    log(f'daily: {nb} symbol batches for {start}..{end} (history from {fs.date()})')
    for bi in range(nb):
        key = f'{start}|{end}|{bi}'
        if key in done:
            continue
        data = _fetch(client, syms[bi * BATCH_DAILY:(bi + 1) * BATCH_DAILY], TimeFrame.Day, fs, fe)
        if not data and not accept_empty:
            log(f'  daily batch {bi} returned nothing (gave up or empty)')
            pending.append(f'daily:{key}')
            continue
        rows, cal = [], Counter()
        for sym, bars in data.items():
            d = np.array([b.timestamp.astimezone(ET).date() for b in bars])
            o = np.array([b.open for b in bars], dtype=float)
            c = np.array([b.close for b in bars], dtype=float)
            v = np.array([b.volume for b in bars], dtype=float)
            cal.update(d.tolist())
            rows += [(sym,) + r for r in screen_daily(d, o, c, v, start, end)]
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO fade_cand VALUES %s ON CONFLICT DO NOTHING', rows)
            if cal:
                psycopg2.extras.execute_values(
                    cur, 'INSERT INTO fade_cal VALUES %s ON CONFLICT (day) DO UPDATE '
                         'SET n = GREATEST(fade_cal.n, EXCLUDED.n)', list(cal.items()))
        conn.commit()
        _mark(conn, 'daily', key)
        n_new += len(rows)
        log(f'  daily batch {bi + 1}/{nb}: {len(data)} symbols with bars, +{len(rows)} candidates '
            f'({time.time() - t0:.0f}s)')
    return pending


def read_cand(conn, start, end):
    return pd.read_sql('SELECT symbol, day, prior_close, open, gap, adv20, prev_day FROM fade_cand '
                       'WHERE day BETWEEN %s AND %s', conn, params=(start, end))


def read_cal(conn, extra_days=()):
    with conn.cursor() as cur:
        cur.execute('SELECT day FROM fade_cal WHERE n >= %s', (CAL_MIN_SYMS,))
        cal = {r[0] for r in cur.fetchall() if r[0].weekday() < 5}
    cal |= set(extra_days)       # a candidate day always counts as a market day
    return sorted(cal)


def _news_fetch(nc, syms, s, e):
    """Articles tagged to any of syms, created in [s, e]. None = the API gave up (caller must not mark done).
    Splits the symbol chunk if the result hits the cap (so nothing is silently truncated)."""
    arts = None
    for attempt in range(6):
        try:
            arts = nc.get_news(NewsRequest(symbols=','.join(sorted(syms)), start=s, end=e, limit=NEWS_LIMIT,
                                           include_content=False)).data.get('news', [])
            break
        except Exception as ex:  # noqa: BLE001
            if attempt == 5:
                log(f'  news GAVE UP on {len(syms)} symbols {s:%Y-%m-%d}: {str(ex)[:80]}')
            time.sleep(2 ** attempt * 3)
    if arts is None:
        return None
    if len(arts) >= NEWS_LIMIT and len(syms) > 1:
        mid = len(syms) // 2
        a, b = _news_fetch(nc, syms[:mid], s, e), _news_fetch(nc, syms[mid:], s, e)
        if a is None or b is None:
            return None
        return list({x.id: x for x in a + b}.values())
    return arts


def stage_news(conn, nc, cand, cal):
    prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
    done = _done(conn, 'news')
    days = sorted(d for d in cand.day.unique() if d.isoformat() not in done)
    no_prev = [d for d in days if d not in prev]
    days = [d for d in days if d in prev]
    log(f'news: {len(days)} days to fetch' + (f' ({len(no_prev)} days without a prior market day skipped)'
                                              if no_prev else ''))
    pending, t0 = [f'news:{d}' for d in no_prev], time.time()
    for i, d in enumerate(days, 1):
        syms = sorted(cand[cand.day == d].symbol)
        p = prev[d]
        s = ET.localize(datetime(p.year, p.month, p.day, 16, 0))
        e = ET.localize(datetime(d.year, d.month, d.day, 9, 29, 59))
        rows, ok = [], True
        for j in range(0, len(syms), BATCH_NEWS):
            chunk = syms[j:j + BATCH_NEWS]
            arts = _news_fetch(nc, chunk, s, e)
            if arts is None:
                ok = False
                break
            for a in arts:
                if not (s <= a.created_at <= e):      # prereg: CREATED in the window (guards updated_at hits)
                    continue
                for sym in set(a.symbols or []) & set(chunk):
                    rows.append((d, sym, a.id, a.created_at, a.headline, len(a.symbols or [])))
            time.sleep(0.33)
        if not ok:
            pending.append(f'news:{d}')
            continue
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO fade_news VALUES %s ON CONFLICT DO NOTHING', rows)
        conn.commit()
        _mark(conn, 'news', d.isoformat())
        if i % 50 == 0 or i == len(days):
            log(f'  news {i}/{len(days)} days ({time.time() - t0:.0f}s)')
    return pending


def stage_minutes(conn, client, cand, accept_empty):
    done = _done(conn, 'minute')
    days = sorted(d for d in cand.day.unique() if d.isoformat() not in done)
    log(f'minute bars: {cand.day.nunique()} candidate days, {len(days)} to fetch')
    pending, t0, nbars, nmissing = [], time.time(), 0, 0
    for i, d in enumerate(days, 1):
        syms = sorted(cand[cand.day == d].symbol)
        s = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
        e = ET.localize(datetime(d.year, d.month, d.day, 15, 59, 59))
        ok = True
        for j in range(0, len(syms), BATCH_MIN):
            chunk = syms[j:j + BATCH_MIN]
            data = _fetch(client, chunk, TimeFrame.Minute, s, e)
            if not data and not accept_empty:
                ok = False          # _fetch gave up (or genuinely empty): never mark done on an empty batch
                break
            nbars += _insert(conn, 'fade_bars_1m', data)
            for sym in chunk:       # partial failure inside _fetch's split path: retry missing symbols alone
                if sym not in data:
                    one = _fetch(client, [sym], TimeFrame.Minute, s, e)
                    nbars += _insert(conn, 'fade_bars_1m', one)
                    if sym not in one:
                        nmissing += 1
        conn.commit()
        if not ok:
            pending.append(f'minute:{d}')
            continue
        _mark(conn, 'minute', d.isoformat())
        if i % 25 == 0 or i == len(days):
            log(f'  minute {i}/{len(days)} days | {nbars:,} bars | {nmissing} symbols without bars | '
                f'{time.time() - t0:.0f}s')
    return pending


def collect(args):
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    client = _client()       # StockHistoricalDataClient (market data only)
    nc = NewsClient(os.environ['APCA_API_KEY_ID'], os.environ['APCA_API_SECRET_KEY'])
    syms = get_universe()
    log(f'universe: {len(syms)} symbols | collecting {start}..{end}')
    pending = stage_daily(conn, client, syms, start, end, args.accept_empty)
    cand = read_cand(conn, start, end)
    cal = read_cal(conn, cand.day.unique())
    log(f'candidates (prior close $10-500, ADV20 >= $50M, gap +4%..+60%): {len(cand)} stock-days '
        f'over {cand.day.nunique()} days | calendar days known: {len(cal)}')
    pending += stage_news(conn, nc, cand, cal)
    pending += stage_minutes(conn, client, cand, args.accept_empty)
    conn.close()
    if pending:
        log(f'INCOMPLETE: {len(pending)} units not marked done (re-run collect): {pending[:10]}')
        sys.exit(2)
    log('DONE collect')


# ── trade logic ───────────────────────────────────────────────────────────────

def short_trade(a, cover_min=COVER_1159, stop_pct=None):
    """a = (m, open, high, low, close) arrays for one stock-day, minute-of-day ascending.
    Short at the open of the first bar in 09:31-09:35; cover at the close of the last bar <= cover_min
    (must be a later bar than the entry bar). Optional stop stop_pct above entry with honest fills."""
    m, o, h, l, c = a
    ent = np.where((m >= ENTRY_FIRST) & (m <= ENTRY_LAST))[0]
    if not ent.size:
        return None
    k = int(ent[0])
    entry = float(o[k])
    if not entry > 0:
        return None
    last = np.where(m <= cover_min)[0]
    if not last.size or int(last[-1]) <= k:
        return None
    kx = int(last[-1])
    kind, fill = 'time', float(c[kx])
    if stop_pct is not None:
        stop = entry * (1 + stop_pct)
        n = len(m)
        for j in range(k, kx + 1):
            if j > k and o[j] >= stop:
                kind, fill = 'gap', float(o[j])
                break
            if h[j] >= stop:
                kind = 'stop'
                fill = float(max(stop, o[j + 1])) if j + 1 < n else float(c[j])
                break
    return {'entry': entry, 'exit': fill, 'kind': kind, 'tmin': int(m[k])}


def net(t, cost):
    """Short return per trade: -(cover/entry - 1) minus a per-side cost on each of the two sides."""
    return -(t['exit'] / t['entry'] - 1) - 2 * cost


def build(cand, bars, cats, want_news, **kw):
    """One short trade per qualifying stock-day. want_news: False = no-news group, True = news group,
    None = both. Gap comes from the daily-bar open (cand.gap)."""
    rows = []
    for r in cand.itertuples():
        if not (GAP_LO <= r.gap <= GAP_HI):
            continue
        has_news = (r.symbol, r.day) in cats
        if want_news is not None and has_news != want_news:
            continue
        a = bars.get((r.symbol, r.day))
        if a is None:
            continue
        t = short_trade(a, **kw)
        if t:
            rows.append({'symbol': r.symbol, 'day': r.day, 'year': r.day.year, 'gap': r.gap, 'news': has_news, **t})
    T = pd.DataFrame(rows, columns=['symbol', 'day', 'year', 'gap', 'news', 'entry', 'exit', 'kind', 'tmin'])
    T['r'] = net(T, COST).astype(float)
    T['rhi'] = net(T, COST_HI).astype(float)
    return T


def summ(label, T, col='r'):
    if T is None or T.empty:
        return f'{label:<48} (no trades)'
    return lg.fmt(label, lg.dci(T[col].values, T.day.values))


# ── data loading for evaluate / check ─────────────────────────────────────────

def load_bars(conn, table, cand, lo, hi):
    """{(symbol, day): (m, o, h, l, c)} for candidate stock-days only; read per half-year to bound memory."""
    keys = pd.MultiIndex.from_frame(cand[['symbol', 'day']])
    out, step = {}, 6
    y, mth = lo.year, 1 if lo.month <= 6 else 7
    while date(y, mth, 1) <= hi:
        a = date(y, mth, 1)
        z = date(y + (mth + step > 12), (mth + step - 1) % 12 + 1, 1)
        b = pd.read_sql(f"""SELECT symbol, (time AT TIME ZONE 'America/New_York')::date AS day,
                (EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') * 60
                 + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York'))::int AS m,
                open, high, low, close FROM {table}
                WHERE time >= %s AND time < %s ORDER BY symbol, time""", conn,
                        params=(ET.localize(datetime(a.year, a.month, a.day)),
                                ET.localize(datetime(z.year, z.month, z.day))))
        if not b.empty:
            b = b[pd.MultiIndex.from_frame(b[['symbol', 'day']]).isin(keys)].reset_index(drop=True)
            M, O, H, L, C = (b[k].values for k in ('m', 'open', 'high', 'low', 'close'))
            for key, idx in b.groupby(['symbol', 'day'], sort=False).indices.items():
                out[key] = (M[idx], O[idx], H[idx], L[idx], C[idx])
        y, mth = z.year, z.month
    return out


def load_news(conn, table, lo, hi):
    nw = pd.read_sql(f'SELECT day, symbol, headline, n_symbols, created_at FROM {table} WHERE day BETWEEN %s AND %s',
                     conn, params=(lo, hi))
    nw['type'] = [article_type(h, n) for h, n in zip(nw.headline, nw.n_symbols)]
    cat = nw[nw.type == 'catalyst']
    return nw, set(zip(cat.symbol, cat.day)), set(zip(nw.symbol, nw.day))


def completeness(conn, cand, syms, start, end):
    """Which units of the collection are not marked done (sealed evaluate refuses if any)."""
    nb = -(-len(syms) // BATCH_DAILY)
    d_done = _done(conn, 'daily')
    miss_daily = [bi for bi in range(nb) if f'{start}|{end}|{bi}' not in d_done]
    days = {d.isoformat() for d in cand.day.unique()}
    miss_min = sorted(days - _done(conn, 'minute'))
    miss_news = sorted(days - _done(conn, 'news'))
    return miss_daily, miss_min, miss_news


# ── check: counts, coverage, look-ahead, data quality (NO returns) ─────────────

def check(args):
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    syms = get_universe()
    cand = read_cand(conn, start, end)
    cal = read_cal(conn, cand.day.unique())
    md, mm, mn = completeness(conn, cand, syms, start, end)
    log(f'CHECK {start}..{end} (counts and coverage only; no returns are computed)')
    log(f'daily batches not done for exactly this range: {len(md)}/{-(-len(syms) // BATCH_DAILY)} | '
        f'candidate days without minute marker: {len(mm)} | without news marker: {len(mn)}')
    log(f'candidates: {len(cand)} stock-days on {cand.day.nunique()} days '
        f'({len(cand) / max(cand.day.nunique(), 1):.1f}/day) | market days known in range: '
        f'{sum(1 for d in cal if start <= d <= end)}')
    prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
    in_rng = [d for d in cal if start <= d <= end]
    log(f'first market day {in_rng[0] if in_rng else None} | first candidate day {cand.day.min() if len(cand) else None} '
        f'(Alpaca history starts 2016-01-04; the 20-day ADV rule needs >= 15 prior bars, so the first ~15 market '
        f'days of 2016 cannot qualify)')
    bad_prev = sum(1 for r in cand.itertuples() if prev.get(r.day) != r.prev_day)
    log(f'look-ahead/data: candidates whose previous daily bar is not the previous market day: {bad_prev}')
    log(f'gap range in table: {cand.gap.min():+.3f} .. {cand.gap.max():+.3f} | '
        f'prior close {cand.prior_close.min():.2f} .. {cand.prior_close.max():.2f} | ADV20 min {cand.adv20.min():,.0f}')
    nw, cats, anyn = load_news(conn, 'fade_news', start, end)
    cd = set(zip(cand.symbol, cand.day))
    log(f'news: {len(nw)} article rows | stock-days with a catalyst article {len(cats & cd)} '
        f'| with any article {len(anyn & cd)} | no-news candidates {len(cd - cats)}')
    if len(nw):
        late = 0
        for r in nw.itertuples():
            cut = ET.localize(datetime(r.day.year, r.day.month, r.day.day, 9, 29, 59))
            pdy = prev.get(r.day)
            lo = ET.localize(datetime(pdy.year, pdy.month, pdy.day, 16, 0)) if pdy else None
            if r.created_at > cut or (lo is not None and r.created_at < lo):
                late += 1
        log(f'look-ahead: articles created outside [16:00 ET prior market day, 09:29:59 ET]: {late} (must be 0)')
    log('\nper-year coverage (candidates | share with catalyst | share with any article | '
        'articles per candidate day):')
    cand['year'] = [d.year for d in cand.day]
    for y, g in cand.groupby('year'):
        ks = set(zip(g.symbol, g.day))
        nws = nw[[d.year == y for d in nw.day]] if len(nw) else nw
        log(f'  {y}: {len(g):>5} | {len(ks & cats) / len(g):5.1%} | {len(ks & anyn) / len(g):5.1%} | '
            f'{len(nws)} article rows over {g.day.nunique()} days')
    bars = load_bars(conn, 'fade_bars_1m', cand, start, end)
    have = [(r.symbol, r.day) in bars for r in cand.itertuples()]
    cand['has_bars'] = have
    ent_ok, exit_ok, late_bar = [], [], []
    open_err = []
    for r in cand.itertuples():
        a = bars.get((r.symbol, r.day))
        if a is None:
            ent_ok.append(False)
            exit_ok.append(False)
            late_bar.append(False)
            continue
        m = a[0]
        ent = np.where((m >= ENTRY_FIRST) & (m <= ENTRY_LAST))[0]
        ent_ok.append(bool(ent.size))
        exit_ok.append(bool(ent.size) and int(np.where(m <= COVER_1159)[0][-1]) > int(ent[0])
                       if (m <= COVER_1159).any() else False)
        late_bar.append(bool((m >= COVER_1559 - 5).any()))
        z = np.where(m == 9 * 60 + 30)[0]
        if z.size:
            open_err.append(abs(a[1][z[0]] / r.open - 1))
    cand['ent_ok'], cand['exit_ok'], cand['late_bar'] = ent_ok, exit_ok, late_bar
    log(f'\nminute bars: {len(bars)} stock-days have bars of {len(cand)} candidates '
        f'({np.mean(have):.1%}); entry bar in 09:31-09:35: {np.mean(ent_ok):.1%}; '
        f'tradable under the primary rule (entry + a later bar <= 11:59): {np.mean(exit_ok):.1%}; '
        f'have a bar at 15:54-15:59: {np.mean(late_bar):.1%}')
    if open_err:
        oe = np.array(open_err)
        log(f'data quality: daily open vs 09:30 bar open, {len(oe)} stock-days with a 09:30 bar: '
            f'within 0.5%: {np.mean(oe < 0.005):.1%}, within 2%: {np.mean(oe < 0.02):.1%}, '
            f'median abs diff {np.median(oe) * 100:.3f}%')
    log('\nper-year tradable stock-days (candidates | with bars | tradable):')
    for y, g in cand.groupby('year'):
        log(f'  {y}: {len(g):>5} | {int(g.has_bars.sum()):>5} | {int(g.exit_ok.sum()):>5}')
    conn.close()


# ── evaluate ──────────────────────────────────────────────────────────────────

def primary_block(T, years, label_hdr, final):
    """Primary rule + the five pass criteria. final=True prints a VERDICT; otherwise it is context only."""
    log(f'\n######## {label_hdr} ########')
    if T.empty:
        log('no trades' + (' -> VERDICT: FAIL' if final else ''))
        return
    s = lg.dci(T.r.values, T.day.values)
    log(lg.fmt('net return @0.15%/side (primary)', s))
    log(lg.fmt('net return @0.30%/side', lg.dci(T.rhi.values, T.day.values)))
    log(f'gross mean (no costs): {(T.r.mean() + 2 * COST) * 100:+.3f}%')
    yr = {}
    for y in years:
        g = T[T.year == y]
        yr[y] = g.r.mean() if len(g) else np.nan
        log(f'  {y}: trades {len(g):>5}  mean {yr[y] * 100:+7.3f}%  pos {np.mean(g.r > 0) if len(g) else 0:4.0%}')
    npos = sum(1 for v in yr.values() if v > 0)
    trimmed = T[T.r <= T.r.quantile(0.99)].r.mean()
    n, mean, _, _, lo, _, _ = s
    a_, b_ = n >= MIN_TRADES, (mean > 0 and lo > 0)
    c_ = npos >= MIN_YEARS_POS
    d_, e_ = T.rhi.mean() > 0, trimmed > 0
    tag = (lambda ok: 'PASS' if ok else 'FAIL') if final else (lambda ok: 'pass' if ok else 'fail')
    log(f'\nCRITERIA (a) >= {MIN_TRADES} trades: {n} -> {tag(a_)}')
    log(f'         (b) mean > 0 and CI lower > 0: {mean * 100:+.3f}% / {lo * 100:+.3f}% -> {tag(b_)}')
    log(f'         (c) positive mean in >= {MIN_YEARS_POS} of {len(years)} years: {npos} -> {tag(c_)}')
    log(f'         (d) mean > 0 at 0.30%/side: {T.rhi.mean() * 100:+.3f}% -> {tag(d_)}')
    log(f'         (e) mean > 0 after dropping best 1% of trades: {trimmed * 100:+.3f}% -> {tag(e_)}')
    if final:
        log(f'VERDICT: {"PASS" if all((a_, b_, c_, d_, e_)) else "FAIL"}')
    else:
        log('(in-sample context; no verdict)')


def report_block(cand, bars, cats, anyn, T_no, years, full_day):
    log('\n######## REPORT-ONLY (never used to decide), @0.15%/side unless stated ########')
    log('-- cover time (no-news, same entry)')
    log(summ('cover at 10:30', build(cand, bars, cats, False, cover_min=COVER_1030)))
    log(summ('cover at 11:59 (primary)', T_no))
    if full_day:
        log(summ('cover at 15:59', build(cand, bars, cats, False, cover_min=COVER_1559)))
    else:
        log('cover at 15:59: skipped (in-sample bars end at 11:59/12:00)')
    log('-- 5% stop above entry, cover 11:59 (honest fills)')
    S = build(cand, bars, cats, False, stop_pct=STOP_PCT)
    log(summ('no-news with 5% stop', S))
    if not S.empty:
        log('  exits: ' + ', '.join(f'{k} {v:.1%}' for k, v in S.kind.value_counts(normalize=True).items()))
    log('-- news gap-ups with the same short rule, and the paired same-day difference')
    T_news = build(cand, bars, cats, True)
    allT = pd.concat([T_no, T_news], ignore_index=True)
    log(summ('news gap-ups (same short rule)', T_news))
    log(summ('no-news gap-ups (primary)', T_no))
    diffs = [g[~g.news].r.mean() - g[g.news].r.mean() for _, g in allT.groupby('day')
             if g.news.any() and (~g.news).any()]
    log(lg.fmt('PAIRED no-news minus news, same day', lg.dci(np.array(diffs), np.arange(len(diffs)))))
    log('-- gap size (no-news, primary)')
    if not T_no.empty:
        log(summ('gap 4-10%', T_no[T_no.gap < 0.10]))
        log(summ('gap > 10%', T_no[T_no.gap >= 0.10]))
    log('-- per-year means (no-news primary | news)')
    for y in years:
        a, b = T_no[T_no.year == y], T_news[T_news.year == y] if not T_news.empty else T_news
        log(f'  {y}: no-news n={len(a):>5} mean {a.r.mean() * 100 if len(a) else float("nan"):+7.3f}% | '
            f'news n={len(b):>4} mean {b.r.mean() * 100 if len(b) else float("nan"):+7.3f}%')
    log('-- news coverage per year (all qualifying gap-ups): candidates | share with catalyst article | '
        'share with any article')
    c2 = cand[(cand.gap >= GAP_LO) & (cand.gap <= GAP_HI)]
    for y in years:
        ks = set(zip(c2[[d.year == y for d in c2.day]].symbol, c2[[d.year == y for d in c2.day]].day))
        if ks:
            log(f'  {y}: {len(ks):>5} | {len(ks & cats) / len(ks):5.1%} | {len(ks & anyn) / len(ks):5.1%}')


def insample_context(conn):
    """2021-2026, same rule, liq_* tables. Report-only context (the idea came from this period)."""
    cand, _ = pickle.load(open(os.path.join(lg.CACHE, 'daily_candidates.pkl'), 'rb'))
    cand = cand[(cand.gap >= GAP_LO) & (cand.gap <= GAP_HI) & (cand.day >= IN_START) & (cand.day <= IN_END)] \
        .reset_index(drop=True)
    nw, cats, anyn = load_news(conn, 'liq_news', IN_START, IN_END)
    bars = load_bars(conn, 'liq_bars_1m', cand, IN_START, IN_END)
    return cand, bars, nw, cats, anyn


def evaluate(args):
    np.random.seed(BOOT_SEED)
    lg.RNG = np.random.default_rng(BOOT_SEED)      # dci() draws from lg.RNG: fixed, order-independent seed
    conn = psycopg2.connect(DSN)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    if args.insample:
        years, tag = list(range(IN_START.year, IN_END.year + 1)), 'INSAMPLE 2021-2026 (liq_* tables)'
        cand, bars, nw, cats, anyn = insample_context(conn)
        full_day = False
    else:
        years, tag = list(range(SEAL_START.year, SEAL_END.year + 1)), 'SEALED 2016-2020 (fade_* tables)'
        cand = read_cand(conn, SEAL_START, SEAL_END)
        cand = cand[(cand.gap >= GAP_LO) & (cand.gap <= GAP_HI)].reset_index(drop=True)
        md, mm, mn = completeness(conn, cand, get_universe(), SEAL_START, SEAL_END)
        if (md or mm or mn) and not args.allow_incomplete:
            raise SystemExit(f'collection incomplete (daily batches {len(md)}, minute days {len(mm)}, news days '
                             f'{len(mn)}); finish `collect` first. Nothing was evaluated.')
        nw, cats, anyn = load_news(conn, 'fade_news', SEAL_START, SEAL_END)
        bars = load_bars(conn, 'fade_bars_1m', cand, SEAL_START, SEAL_END)
        full_day = True
    ck = set(zip(cand.symbol, cand.day))
    log(f'{tag}\ncandidate stock-days {len(cand)} | with minute bars {sum(1 for k in ck if k in bars)} | '
        f'with a catalyst article {len(ck & cats)} | no-news {len(ck - cats)}')
    T_no = build(cand, bars, cats, False)
    log(f'tradable no-news stock-days (entry bar + later cover bar): {len(T_no)}')
    primary_block(T_no, years, 'PRE-REGISTERED: short no-news gap-ups (+4%..+60%), enter 09:31-09:35, '
                  'cover 11:59, no stop', final=not args.insample)
    report_block(cand, bars, cats, anyn, T_no, years, full_day)
    if full_day:
        log('\n######## REPORT-ONLY: 2021-2026 with the same rule (in-sample; context only) ########')
        try:
            c2, b2, _, k2, _ = insample_context(conn)
            A, B = build(c2, b2, k2, False), build(c2, b2, k2, True)
            log(summ('2021-2026 no-news (same short rule)', A))
            log(summ('2021-2026 news (same short rule)', B))
        except Exception as ex:  # noqa: BLE001
            log(f'(skipped: {type(ex).__name__}: {str(ex)[:100]})')
    conn.close()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'evaluate_{"insample" if args.insample else "sealed"}_{ts}.txt')
    open(path, 'w', encoding='utf-8').write('\n'.join(_BUF) + '\n')
    log(f'\nDONE evaluate (output saved to {path})')


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('collect', 'check'):
        s = sub.add_parser(name)
        s.add_argument('--start', default=SEAL_START.isoformat())
        s.add_argument('--end', default=SEAL_END.isoformat())
        if name == 'collect':
            s.add_argument('--accept-empty', action='store_true')
    e = sub.add_parser('evaluate')
    e.add_argument('--insample', action='store_true')
    e.add_argument('--allow-incomplete', action='store_true')
    args = p.parse_args()
    {'collect': collect, 'check': check, 'evaluate': evaluate}[args.cmd](args)


if __name__ == '__main__':
    main()
