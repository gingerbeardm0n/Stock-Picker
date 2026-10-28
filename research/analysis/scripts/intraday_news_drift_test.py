"""Drift after catalyst headlines that break DURING the trading day, delayed entry, 2016-2026.
PRE-REGISTERED in docs/PREREG_2026_10_INTRADAY_NEWS_DRIFT.md (committed before any intraday-headline data was
pulled). One look at the result; nothing here may change after `evaluate` has been run.

Rule (see the doc for the full text; this file implements it literally):
  universe   same US common-stock list as liquid_gap_orb_test.universe(). Primary tier: prior close $10-$500 and
             prior-20-trading-day average dollar volume (close x volume, prior days only) >= $50M.
  event      Alpaca/Benzinga article tagged to the symbol, CREATED 10:00:00-14:59:59 ET on a market day, typed
             `catalyst` by premarket_news_test.article_type (unchanged); fresh = no earlier catalyst article for
             the symbol created since 16:00 ET the prior market day; first qualifying event per symbol-day.
             t0 = the one-minute bar whose minute contains created_at.
  reaction   P_ref = close of the last 1-min bar starting before t0 and >= t0-10min (none: no trade);
             P_react = close of the last bar starting <= t0+1min and >= t0-10min;
             r_react = P_react / P_ref - 1; trade if |r_react| >= 1.0%; long if up, short if down
  trade      entry = open of the first 1-min bar starting t0+2..t0+6 (none: no trade); exit = close of the last
             bar starting <= entry+29 min and <= 15:59 (30-minute hold); no stop; no daily cap
  return     long: exit/entry-1; short: -(exit/entry-1); minus 2 x cost. Cost 0.15%/side primary, 0.30% robustness
  period     2016-01-04 .. 2026-10-23 decides; CIs: day-clustered bootstrap (liquid_gap_orb_test.dci)
  pass bar   (a) >= 1,000 trades (b) mean > 0 @0.15% and CI lower bound > 0 (c) mean > 0 in 2016-2020 AND
             2021-2026 (d) positive mean in >= 6 of the 11 calendar years (e) mean > 0 @0.30% (f) mean > 0
             after dropping the best 1% of trades

Ambiguities resolved (closest to the template no_news_gap_fade_test.py / liquid_gap_orb_test.py unless the prereg
is explicit):
  * ADV uses the symbol's own prior 20 daily bars with min_periods=15; prior close = close of the previous daily
    bar (its date is stored as prev_day and checked against the market-day calendar).
  * Tier boundaries (the prereg's ranges overlap at $10): primary = 10 <= prior close <= 500 and ADV >= $50M;
    small = (1 <= prior close < 10 and ADV >= $2M) OR (10 <= prior close <= 500 and $2M <= ADV < $50M). The two
    tiers are disjoint. Each symbol-day gets one tier ('P' or 'S').
  * News filter on the Alpaca endpoint is on updated_at, NOT created_at (verified: a one-minute window around an
    article's created_at returned nothing when updated_at was days later). So the request window is
    [16:00 ET prior market day, 23:59:59 ET of the day] and articles are then kept only if
    created_at >= 16:00 prior market day and created_at < 15:00:00 ET that day (created_at exactly 10:00:00 and
    14:59:59 are in; 15:00:00 is out; sub-second times below 15:00:00 are in). Articles created in the window but
    first edited after 23:59:59 ET the same day are missed (about 1% of articles); that can only remove events,
    or in rare cases make a later catalyst look fresh; it never adds look-ahead.
  * News is fetched WITHOUT a symbol filter and paginated to the end (50 per page, no limit passed, so the SDK
    default loops until the API returns no next_page_token; it cannot truncate). I use the raw REST call so each
    page is throttled and retried individually. Pagination aborts (day not marked done) after 3000 pages.
    Kept rows: article tagged to >= 1 symbol that is in that day's universe (either tier). Stored per
    (day, symbol, article): n_symbols = number of symbols tagged on the article (the template's convention).
  * Freshness is evaluated over ALL stored articles of the symbol since 16:00 prior market day, sorted by
    (created_at, article_id). Only `catalyst` articles block freshness (roundups / reaction pieces do not).
    Consequence: the event is simply the symbol-day's first catalyst article, if it was created 10:00-15:00.
    Ties at the same created_at: the lower article_id is "earlier".
  * Minute bars (09:30-15:59 ET, SIP, raw) are collected for symbol-days with >= 1 article of ANY type created
    10:00:00-14:59:59 (placebo needs the non-catalyst ones). Ordinary minute-of-day indexing; absent minutes are
    simply absent (thin trading).
  * "last bar that starts before t0 and >= t0-10" etc. are on bar START minute. A bar starting exactly at t0-10 is
    allowed. If no bar starts in t0..t0+1, P_react is the same bar as P_ref, r_react = 0, and no trade results.
  * |r_react| >= 1.0% compares with a 1e-12 tolerance so 100 -> 101 counts as exactly 1.0%.
  * Exit bar: if the entry bar is the last bar allowed, exit = close of the entry bar itself (the prereg does
    not require a later bar, and says every qualifying event trades).
  * Holds: 10 / 30 / 60 minutes mean exit limit = entry minute + 9 / 29 / 59 (the primary "+29"); "to 15:59" is
    the 15:59 bar; all capped at 15:59.
  * Report-only fast entry (open of the t0+1 bar): the bar must start exactly at t0+1. To avoid look-ahead (the
    t0+1 bar's close is unknown at its open), its reaction uses bars starting <= t0 only (P_react_fast = close
    of the last bar starting in [t0-10, t0]); hold 30 min as the primary. Direction and threshold from that.
  * Report-only placebo: the symbol-day's FIRST article of any type (since 16:00 prior market day) is a
    non-catalyst (roundup / reaction type) created 10:00:00-14:59:59 AND the symbol-day has no catalyst article
    anywhere in the window. Same reaction/entry/exit rule; primary-tier cost.
  * Report-only small tier: same event rule, small-tier symbol-days, cost 0.5%/side (no robustness doubling).
  * Terciles split the primary trades by |r_react| (>= 1%) with pandas qcut.
  * "Best 1%" dropped by the template's method: keep trades with net <= the 99th percentile of net.
  * Alpaca SIP history starts 2016-01-04; symbols need >= 15 prior daily bars, so ~2016-01-26 is the first
    possible event day. Nothing is imputed.

Stages (each caches in the DB and resumes; tables prefixed ind_):
  python research/analysis/scripts/intraday_news_drift_test.py collect [--start 2016-01-04 --end 2026-10-23]
        [--accept-empty]     daily bars -> tiered universe -> news -> 1-min bars for event symbol-days
  python research/analysis/scripts/intraday_news_drift_test.py check [--start .. --end ..]
        counts / coverage / look-ahead checks only. Prints NO returns of any kind.
  python research/analysis/scripts/intraday_news_drift_test.py evaluate     the one sealed look (do not run early)
  python research/analysis/scripts/intraday_news_drift_test.py selftest     synthetic unit tests, no DB / no network
A unit of work whose fetch gave up is NOT marked done; collect exits with code 2 and lists what is pending.
Re-run collect to retry. --accept-empty marks currently-empty units done (use only after a retry confirmed they
are genuinely empty).
"""
import argparse
import os
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
import liquid_gap_orb_test as lg  # noqa: E402  (universe cache, dci bootstrap, fmt, DSN)
from premarket_news_test import article_type  # noqa: E402

from alpaca.data.historical.news import NewsClient  # noqa: E402
from alpaca.data.requests import NewsRequest  # noqa: E402

warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')

DSN = lg.DSN
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'intraday_news'))
# research/analysis/outputs/ is already covered by the repo .gitignore (verified with git check-ignore)
START_DEFAULT, END_DEFAULT = date(2016, 1, 4), date(2026, 10, 23)
PRICE_LO, PRICE_HI = 10, 500                  # primary tier price band (inclusive)
SMALL_PRICE_LO = 1                            # small tier: 1 <= pc < 10 (disjoint from primary)
ADV_PRIMARY, ADV_SMALL = 50e6, 2e6
COST, COST_HI, COST_SMALL = 0.0015, 0.003, 0.005
THR = 0.01
THR_EPS = 1e-12
EV_LO, EV_HI = 10 * 3600, 15 * 3600           # article created in [10:00:00, 15:00:00) ET, seconds of day
LAST_MIN = 15 * 60 + 59
PRE_MIN, ENTRY_LO, ENTRY_HI = 10, 2, 6        # reference lookback, entry window t0+2..t0+6 (minutes)
HOLDS = {'x10': 9, 'x30': 29, 'x60': 59, 'xc': None}   # exit limit offsets from the entry minute; None = 15:59
HISTORY_DAYS = 50
BATCH_DAILY, BATCH_MIN = 200, 50
NEWS_PAGE_SLEEP, MAX_NEWS_PAGES = 0.3, 3000
MIN_SLEEP = 0.25
CAL_MIN_SYMS = 20
BOOT_SEED = 20261028
MIN_TRADES, MIN_YEARS_POS = 1000, 6
HALVES = ((2016, 2020), (2021, 2026))

DDL = """
CREATE TABLE IF NOT EXISTS ind_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS ind_news (
    day date, symbol varchar(10), article_id bigint, created_at timestamptz, headline text,
    n_symbols int, PRIMARY KEY (day, symbol, article_id));
CREATE TABLE IF NOT EXISTS ind_cand (
    symbol varchar(10), day date, tier char(1), prior_close double precision, adv20 double precision,
    prev_day date, PRIMARY KEY (symbol, day));
CREATE INDEX IF NOT EXISTS ind_cand_day ON ind_cand (day);
CREATE TABLE IF NOT EXISTS ind_cal (day date PRIMARY KEY, n int);
CREATE TABLE IF NOT EXISTS ind_done (kind text, key text, PRIMARY KEY (kind, key));
"""

_BUF = []


def log(*a):
    s = ' '.join(str(x) for x in a)
    _BUF.append(s)
    print(s, flush=True)


# ── resume markers ───────────────────────────────────────────────────────────

def _done(conn, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT key FROM ind_done WHERE kind = %s', (kind,))
        return {r[0] for r in cur.fetchall()}


def _mark(conn, kind, key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO ind_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (kind, key))
    conn.commit()


def get_universe():
    # liquid_gap_orb_test.universe() would call Alpaca's trading API (asset list) if its cache were missing.
    # This experiment must only touch market-data endpoints, so insist on the cached list.
    if not os.path.exists(os.path.join(lg.CACHE, 'universe.pkl')):
        raise SystemExit(f'universe cache missing at {lg.CACHE}\\universe.pkl; refusing to call the trading API')
    return lg.universe()


# ── collection ───────────────────────────────────────────────────────────────

def tier_of(pc, adv):
    """Vectorised tier: 'P' primary, 'S' small, '' neither. pc/adv are float arrays (NaN -> '')."""
    pc, adv = np.asarray(pc, float), np.asarray(adv, float)
    with np.errstate(invalid='ignore'):
        in_band = (pc >= PRICE_LO) & (pc <= PRICE_HI)
        prim = in_band & (adv >= ADV_PRIMARY)
        small = ((pc >= SMALL_PRICE_LO) & (pc < PRICE_LO) & (adv >= ADV_SMALL)) \
            | (in_band & (adv >= ADV_SMALL) & (adv < ADV_PRIMARY))
    return np.where(prim, 'P', np.where(small, 'S', ''))


def screen_daily(d, c, v, start, end):
    """Rows (day, tier, prior_close, adv20, prev_day) for one symbol from its ascending daily bars.
    Look-ahead guard: prior close and the 20-day dollar-volume average use bars strictly BEFORE day k."""
    if len(d) < 16:
        return []
    pc = np.r_[np.nan, c[:-1]]
    pday = np.concatenate([np.array([None], dtype=object), d[:-1]])
    adv = pd.Series(np.r_[np.nan, (c * v)[:-1]]).rolling(20, min_periods=15).mean().values
    tier = tier_of(pc, adv)
    m = (d >= start) & (d <= end) & (tier != '')
    return [(d[k], str(tier[k]), float(pc[k]), float(adv[k]), pday[k]) for k in np.where(m)[0]]


def stage_daily(conn, client, syms, start, end, accept_empty=False):
    fs = ET.localize(datetime.combine(start - timedelta(days=HISTORY_DAYS), datetime.min.time()))
    fe = ET.localize(datetime(end.year, end.month, end.day, 23))
    done = _done(conn, 'daily')
    nb = -(-len(syms) // BATCH_DAILY)
    pending, t0 = [], time.time()
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
            c = np.array([b.close for b in bars], dtype=float)
            v = np.array([b.volume for b in bars], dtype=float)
            cal.update(d.tolist())
            rows += [(sym, r[0], r[1], r[2], r[3], r[4]) for r in screen_daily(d, c, v, start, end)]
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(
                    cur, 'INSERT INTO ind_cand (symbol, day, tier, prior_close, adv20, prev_day) VALUES %s '
                         'ON CONFLICT DO NOTHING', rows, page_size=5000)
            if cal:
                psycopg2.extras.execute_values(
                    cur, 'INSERT INTO ind_cal VALUES %s ON CONFLICT (day) DO UPDATE '
                         'SET n = GREATEST(ind_cal.n, EXCLUDED.n)', list(cal.items()))
        conn.commit()
        _mark(conn, 'daily', key)
        log(f'  daily batch {bi + 1}/{nb}: {len(data)} symbols with bars, +{len(rows)} symbol-days '
            f'({time.time() - t0:.0f}s)')
    return pending


def read_cal(conn, extra_days=()):
    with conn.cursor() as cur:
        cur.execute('SELECT day FROM ind_cal WHERE n >= %s', (CAL_MIN_SYMS,))
        cal = {r[0] for r in cur.fetchall() if r[0].weekday() < 5}
    cal |= set(extra_days)
    return sorted(cal)


def cand_days(conn, start, end):
    with conn.cursor() as cur:
        cur.execute('SELECT DISTINCT day FROM ind_cand WHERE day BETWEEN %s AND %s ORDER BY day', (start, end))
        return [r[0] for r in cur.fetchall()]


def _news_pages(nc, s, e):
    """All raw article dicts with updated_at in [s, e] (the API filters on updated_at). Fully paginated.
    None = gave up (caller must not mark the day done)."""
    out, tok = [], None
    for _ in range(MAX_NEWS_PAGES):
        resp = None
        t_req = time.time()
        for attempt in range(6):
            try:
                p = NewsRequest(start=s, end=e, limit=50, include_content=False, page_token=tok).to_request_fields()
                resp = nc.get(path='/news', data=p)
                break
            except Exception as ex:  # noqa: BLE001
                msg = str(ex)
                if attempt == 5:
                    log(f'  news GAVE UP {s:%Y-%m-%d %H:%M}: {msg[:80]}')
                time.sleep(2 ** attempt * (5 if '429' in msg or 'rate' in msg.lower() else 1))
        if resp is None:
            return None
        out += resp.get('news', [])
        tok = resp.get('next_page_token')
        time.sleep(max(0.0, NEWS_PAGE_SLEEP - (time.time() - t_req)))   # <= ~200 requests/min
        if not tok:
            return out
    log(f'  news pagination exceeded {MAX_NEWS_PAGES} pages {s:%Y-%m-%d}: treating as failure')
    return None


def stage_news(conn, nc, start, end):
    cal = read_cal(conn, cand_days(conn, start, end))
    prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
    done = _done(conn, 'news')
    days = [d for d in cand_days(conn, start, end) if d.isoformat() not in done]
    no_prev = [d for d in days if d not in prev]
    days = [d for d in days if d in prev]
    log(f'news: {len(days)} days to fetch' + (f' ({len(no_prev)} days without a prior market day skipped)'
                                              if no_prev else ''))
    pending, t0, nart = [f'news:{d}' for d in no_prev], time.time(), 0
    for i, d in enumerate(days, 1):
        with conn.cursor() as cur:
            cur.execute('SELECT symbol FROM ind_cand WHERE day = %s', (d,))
            uni = {r[0] for r in cur.fetchall()}
        p = prev[d]
        s = ET.localize(datetime(p.year, p.month, p.day, 16, 0))
        e_api = ET.localize(datetime(d.year, d.month, d.day, 23, 59, 59))
        cut = ET.localize(datetime(d.year, d.month, d.day, 15, 0, 0))
        arts = _news_pages(nc, s, e_api)
        if arts is None:
            pending.append(f'news:{d}')
            continue
        rows, seen = [], set()
        for a in arts:
            if a['id'] in seen:
                continue
            seen.add(a['id'])
            ca = pd.Timestamp(a['created_at']).to_pydatetime()
            if not (s <= ca < cut):        # created_at inside [16:00 prior market day, 15:00:00 ET)
                continue
            syms = a.get('symbols') or []
            for sym in set(syms) & uni:
                rows.append((d, sym, a['id'], ca, a.get('headline'), len(syms)))
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO ind_news VALUES %s ON CONFLICT DO NOTHING', rows)
        conn.commit()
        _mark(conn, 'news', d.isoformat())
        nart += len(seen)
        if i % 25 == 0 or i == len(days):
            log(f'  news {i}/{len(days)} days | {nart:,} raw articles | {time.time() - t0:.0f}s')
    return pending


def event_symbols(conn, d):
    """Symbols with >= 1 article of any type created 10:00:00-14:59:59 ET on day d."""
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT symbol FROM ind_news WHERE day = %s
                       AND (created_at AT TIME ZONE 'America/New_York')::time >= '10:00:00'
                       AND (created_at AT TIME ZONE 'America/New_York')::time < '15:00:00'
                       ORDER BY symbol""", (d,))
        return [r[0] for r in cur.fetchall()]


def event_days(conn, start, end):
    with conn.cursor() as cur:
        cur.execute("""SELECT DISTINCT day FROM ind_news WHERE day BETWEEN %s AND %s
                       AND (created_at AT TIME ZONE 'America/New_York')::time >= '10:00:00'
                       AND (created_at AT TIME ZONE 'America/New_York')::time < '15:00:00'
                       ORDER BY day""", (start, end))
        return [r[0] for r in cur.fetchall()]


def stage_minutes(conn, client, start, end, accept_empty):
    done = _done(conn, 'minute')
    alld = event_days(conn, start, end)
    days = [d for d in alld if d.isoformat() not in done]
    log(f'minute bars: {len(alld)} days with event symbol-days, {len(days)} to fetch')
    pending, t0, nbars, nmissing, nsd = [], time.time(), 0, 0, 0
    for i, d in enumerate(days, 1):
        syms = event_symbols(conn, d)
        s = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
        e = ET.localize(datetime(d.year, d.month, d.day, 15, 59, 59))
        ok = True
        for j in range(0, len(syms), BATCH_MIN):
            chunk = syms[j:j + BATCH_MIN]
            data = _fetch(client, chunk, TimeFrame.Minute, s, e)
            if not data and not accept_empty:
                ok = False          # _fetch gave up (or genuinely empty): never mark done on an empty batch
                break
            nbars += _insert(conn, 'ind_bars_1m', data)
            miss = [x for x in chunk if x not in data]
            if miss and data:       # partial result: retry the missing ones once, together (split-path guard)
                one = _fetch(client, miss, TimeFrame.Minute, s, e)
                nbars += _insert(conn, 'ind_bars_1m', one)
                miss = [x for x in miss if x not in one]
            nmissing += len(miss)
            time.sleep(MIN_SLEEP)
        conn.commit()
        nsd += len(syms)
        if not ok:
            pending.append(f'minute:{d}')
            continue
        _mark(conn, 'minute', d.isoformat())
        if i % 25 == 0 or i == len(days):
            log(f'  minute {i}/{len(days)} days | {nsd:,} symbol-days | {nbars:,} bars | '
                f'{nmissing} without bars | {time.time() - t0:.0f}s')
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
    cd = cand_days(conn, start, end)
    log(f'tiered symbol-days on {len(cd)} days in range')
    pending += stage_news(conn, nc, start, end)
    pending += stage_minutes(conn, client, start, end, args.accept_empty)
    conn.close()
    if pending:
        log(f'INCOMPLETE: {len(pending)} units not marked done (re-run collect): {pending[:10]}')
        sys.exit(2)
    log('DONE collect')


# ── event / trade logic (pure functions; exercised by selftest) ──────────────

def pick_events(arts):
    """arts: list of (key, article_id, typ, sod) for ONE symbol-day, all articles created since 16:00 ET of the
    prior market day and before 15:00:00 ET. key = created_at as a monotonic number (epoch seconds), typ in
    {'catalyst','roundup','reaction'}, sod = seconds of day ET of created_at.
    Returns (catalyst_event, placebo_event); each is the sod of the event article or None.
    catalyst_event: the first catalyst article (freshness: no earlier catalyst), if created in [10:00:00, 15:00:00).
    placebo_event: no catalyst anywhere in the group and the first article (any type) is created in the window."""
    if not arts:
        return None, None
    arts = sorted(arts, key=lambda x: (x[0], x[1]))
    cat = [x for x in arts if x[2] == 'catalyst']
    if cat:
        f = cat[0]
        return (f[3] if EV_LO <= f[3] < EV_HI else None), None
    f = arts[0]
    return None, (f[3] if EV_LO <= f[3] < EV_HI else None)


def _last(m, lo, hi):
    idx = np.where((m >= lo) & (m <= hi))[0]
    return int(idx[-1]) if idx.size else -1


def _first(m, lo, hi):
    idx = np.where((m >= lo) & (m <= hi))[0]
    return int(idx[0]) if idx.size else -1


def _exit_idx(m, k, off):
    lim = LAST_MIN if off is None else min(int(m[k]) + off, LAST_MIN)
    return _last(m, int(m[k]), lim)


def simulate_event(a, t0):
    """a = (m, open, high, low, close) arrays for one symbol-day (minute-of-day ascending); t0 = minute of day of
    the headline's bar. Returns None when there is no usable P_ref (no trade under any variant), else a dict with
    the reaction and, where the bars exist, the entry and exit prices of every variant (NaN = no such trade).
    No threshold is applied here."""
    m, o, h, l, c = a
    nan = float('nan')
    ref = _last(m, t0 - PRE_MIN, t0 - 1)
    if ref < 0 or not c[ref] > 0:
        return None
    react = _last(m, t0 - PRE_MIN, t0 + 1)
    ev = {'r': float(c[react] / c[ref] - 1), 'entry': nan, 'emin': -1, 'x10': nan, 'x30': nan, 'x60': nan,
          'xc': nan, 'fr': nan, 'fentry': nan, 'fx30': nan}
    k = _first(m, t0 + ENTRY_LO, t0 + ENTRY_HI)
    if k >= 0 and o[k] > 0 and m[k] <= LAST_MIN:
        ev['entry'], ev['emin'] = float(o[k]), int(m[k])
        for name, off in HOLDS.items():
            ev[name] = float(c[_exit_idx(m, k, off)])
    # report-only fast entry: bar starting exactly t0+1; reaction from bars starting <= t0 only (no look-ahead)
    kf = _first(m, t0 + 1, t0 + 1)
    if kf >= 0 and o[kf] > 0:
        rf = _last(m, t0 - PRE_MIN, t0)
        ev['fr'] = float(c[rf] / c[ref] - 1)
        ev['fentry'] = float(o[kf])
        ev['fx30'] = float(c[_exit_idx(m, kf, HOLDS['x30'])])
    return ev


def signed_gross(r, entry, exit_):
    """Gross signed return of a trade in the direction of the reaction r (long if r>0, short if r<0)."""
    s = 1.0 if r > 0 else -1.0
    return s * (exit_ / entry - 1)


def passes(r, thr=THR):
    return abs(r) >= thr - THR_EPS


def net(gross, cost):
    return gross - 2 * cost


# ── data loading ─────────────────────────────────────────────────────────────

def half_years(lo, hi):
    y, mth = lo.year, 1 if lo.month <= 6 else 7
    while date(y, mth, 1) <= hi:
        a = date(y, mth, 1)
        z = date(y + (mth + 6 > 12), (mth + 6 - 1) % 12 + 1, 1)
        yield a, z
        y, mth = z.year, z.month


def load_bars_chunk(conn, a, z):
    """{(symbol, day): (m, o, h, l, c)} for all ind_bars_1m rows in [a, z)."""
    b = pd.read_sql("""SELECT symbol, (time AT TIME ZONE 'America/New_York')::date AS day,
            (EXTRACT(HOUR FROM time AT TIME ZONE 'America/New_York') * 60
             + EXTRACT(MINUTE FROM time AT TIME ZONE 'America/New_York'))::int AS m,
            open, high, low, close FROM ind_bars_1m
            WHERE time >= %s AND time < %s ORDER BY symbol, time""", conn,
                    params=(ET.localize(datetime(a.year, a.month, a.day)),
                            ET.localize(datetime(z.year, z.month, z.day))))
    out = {}
    if b.empty:
        return out
    M, O, H, L, C = (b[k].values for k in ('m', 'open', 'high', 'low', 'close'))
    for key, idx in b.groupby(['symbol', 'day'], sort=False).indices.items():
        out[key] = (M[idx], O[idx], H[idx], L[idx], C[idx])
    return out


def load_news(conn, lo, hi):
    """Articles with their symbol-day tier, plus time keys. Only rows of tiered symbol-days exist (joined)."""
    nw = pd.read_sql("""SELECT n.day, n.symbol, n.article_id, n.created_at, n.headline, n.n_symbols, c.tier
                        FROM ind_news n JOIN ind_cand c ON c.symbol = n.symbol AND c.day = n.day
                        WHERE n.day BETWEEN %s AND %s""", conn, params=(lo, hi))
    if nw.empty:
        return nw
    nw['type'] = [article_type(h, n) for h, n in zip(nw.headline, nw.n_symbols)]
    ts = pd.to_datetime(nw.created_at, utc=True)
    et = ts.dt.tz_convert('America/New_York')
    nw['key'] = (ts - pd.Timestamp('1970-01-01', tz='UTC')).dt.total_seconds()
    nw['sod'] = et.dt.hour * 3600 + et.dt.minute * 60 + et.dt.second + et.dt.microsecond / 1e6
    return nw


def events_from_news(nw):
    """[(symbol, day, tier, kind, sod)] where kind is 'catalyst' or 'placebo'."""
    out = []
    if nw.empty:
        return out
    for (sym, day), g in nw.groupby(['symbol', 'day'], sort=False):
        arts = list(zip(g.key.values, g.article_id.values, g.type.values, g.sod.values))
        ce, pe = pick_events(arts)
        tier = g.tier.iloc[0]
        if ce is not None:
            out.append((sym, day, tier, 'catalyst', float(ce)))
        if pe is not None:
            out.append((sym, day, tier, 'placebo', float(pe)))
    return out


TCOLS = ['symbol', 'day', 'year', 'tier', 'kind', 'hour', 'r_react', 'g10', 'g30', 'g60', 'gc', 'fr', 'fg30']


def build_trades(conn, evs, lo, hi):
    """One row per event with usable P_ref; gross signed returns of every variant (NaN where no trade).
    Bars are read half a year at a time to bound memory."""
    by_key = {}
    for e in evs:
        by_key.setdefault((e[0], e[1]), []).append(e)
    rows = []
    for a, z in half_years(lo, hi):
        bars = load_bars_chunk(conn, a, z)
        for key, a_ in bars.items():
            for sym, day, tier, kind, sod in by_key.get(key, ()):
                ev = simulate_event(a_, int(sod // 60))
                if ev is None:
                    continue
                r = ev['r']
                g = {}
                for nme, col in (('x10', 'g10'), ('x30', 'g30'), ('x60', 'g60'), ('xc', 'gc')):
                    g[col] = signed_gross(r, ev['entry'], ev[nme]) if ev['entry'] == ev['entry'] else np.nan
                fg = signed_gross(ev['fr'], ev['fentry'], ev['fx30']) if ev['fentry'] == ev['fentry'] and ev['fr'] != 0 \
                    else np.nan
                rows.append((sym, day, day.year, tier, kind, int(sod // 3600), r, g['g10'], g['g30'], g['g60'],
                             g['gc'], ev['fr'], fg))
    T = pd.DataFrame(rows, columns=TCOLS)
    return T


def completeness(conn, syms, start, end):
    nb = -(-len(syms) // BATCH_DAILY)
    d_done = _done(conn, 'daily')
    miss_daily = [bi for bi in range(nb) if f'{start}|{end}|{bi}' not in d_done]
    miss_news = sorted(d.isoformat() for d in cand_days(conn, start, end))
    miss_news = sorted(set(miss_news) - _done(conn, 'news'))
    miss_min = sorted({d.isoformat() for d in event_days(conn, start, end)} - _done(conn, 'minute'))
    return miss_daily, miss_news, miss_min


# ── check: counts, coverage, look-ahead, data quality (NO returns) ────────────

def check(args):
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    syms = get_universe()
    md, mn, mm = completeness(conn, syms, start, end)
    log(f'CHECK {start}..{end} (counts and coverage only; no returns of any kind are computed)')
    log(f'daily batches not done for exactly this range: {len(md)}/{-(-len(syms) // BATCH_DAILY)} | '
        f'cand days without news marker: {len(mn)} | event days without minute marker: {len(mm)}')
    cand = pd.read_sql('SELECT tier, day, prev_day, prior_close, adv20 FROM ind_cand WHERE day BETWEEN %s AND %s',
                       conn, params=(start, end))
    cal = read_cal(conn, cand.day.unique())
    log(f'symbol-days: {len(cand)} on {cand.day.nunique()} days | primary {int((cand.tier == "P").sum())} | '
        f'small {int((cand.tier == "S").sum())} | market days known in range: '
        f'{sum(1 for d in cal if start <= d <= end)}')
    if len(cand):
        prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
        bad = int(sum(1 for d, p in zip(cand.day, cand.prev_day) if prev.get(d) != p))
        log(f'look-ahead/data: symbol-days whose previous daily bar is not the previous market day: {bad}')
        for t, nm in (('P', 'primary'), ('S', 'small')):
            g = cand[cand.tier == t]
            if len(g):
                log(f'  {nm}: prior close {g.prior_close.min():.2f}..{g.prior_close.max():.2f} | '
                    f'ADV20 {g.adv20.min():,.0f}..{g.adv20.max():,.0f}')
        log(f'  first market day {min(d for d in cal if d >= start)} | first symbol-day {cand.day.min()}')
    nw = load_news(conn, start, end)
    log(f'\nnews: {len(nw)} article-symbol rows | {nw.article_id.nunique() if len(nw) else 0} distinct articles')
    if len(nw):
        prev = {cal[k]: cal[k - 1] for k in range(1, len(cal))}
        bad = 0
        for r in nw.itertuples():
            pd_ = prev.get(r.day)
            lo_ = ET.localize(datetime(pd_.year, pd_.month, pd_.day, 16, 0)) if pd_ else None
            et = pd.Timestamp(r.created_at).tz_convert('America/New_York')
            hi_ = ET.localize(datetime(r.day.year, r.day.month, r.day.day, 15, 0, 0))
            if et >= hi_ or (lo_ is not None and et < lo_):
                bad += 1
        log(f'look-ahead: article rows created outside [16:00 ET prior market day, 15:00:00 ET): {bad} (must be 0)')
        nw['year'] = [d.year for d in nw.day]
        evs = events_from_news(nw)
        E = pd.DataFrame(evs, columns=['symbol', 'day', 'tier', 'kind', 'sod'])
        bad_ev = int(((E.sod < EV_LO) | (E.sod >= EV_HI)).sum()) if len(E) else 0
        log(f'look-ahead: events created outside [10:00:00, 15:00:00): {bad_ev} (must be 0)')
        inr = nw[(nw.sod >= EV_LO) & (nw.sod < EV_HI)]
        log('\nper-year: raw article-symbol rows | in-window rows (10:00-15:00) | distinct in-window symbol-days | '
            'catalyst events P / S | placebo events P / S')
        for y in sorted(nw.year.unique()):
            g = nw[nw.year == y]
            gi = inr[inr.year == y]
            e = E[[d.year == y for d in E.day]] if len(E) else E
            c_ = lambda k, t: int(((e.kind == k) & (e.tier == t)).sum()) if len(e) else 0  # noqa: E731
            log(f'  {y}: {len(g):>7} | {len(gi):>6} | {len(gi.drop_duplicates(["symbol", "day"])):>6} | '
                f'{c_("catalyst", "P"):>5} / {c_("catalyst", "S"):>5} | {c_("placebo", "P"):>5} / {c_("placebo", "S"):>5}')
        sd = inr.drop_duplicates(['symbol', 'day'])
        log(f'\nin-window symbol-days needing minute bars: {len(sd)}')
        # structure only: P_ref present, entry bar present, entry strictly after t0+1. No reaction/return computed.
        by_key = {}
        for e in evs:
            by_key.setdefault((e[0], e[1]), []).append(e)
        have = Counter()
        struct = Counter()
        viol = 0
        for a, z in half_years(start, end):
            bars = load_bars_chunk(conn, a, z)
            for key in bars:
                have[key[1].year] += 1
            for key, a_ in bars.items():
                for sym, day, tier, kind, sod in by_key.get(key, ()):
                    t0 = int(sod // 60)
                    m = a_[0]
                    ref = _last(m, t0 - PRE_MIN, t0 - 1)
                    k = _first(m, t0 + ENTRY_LO, t0 + ENTRY_HI)
                    struct[(day.year, kind, tier, 'event')] += 1
                    if ref >= 0:
                        struct[(day.year, kind, tier, 'ref')] += 1
                    if ref >= 0 and k >= 0:
                        struct[(day.year, kind, tier, 'tradable')] += 1
                        if int(m[k]) < t0 + 2:
                            viol += 1
        log(f'look-ahead: tradable events whose entry bar starts before t0+2: {viol} (must be 0)')
        log('\nper-year minute-bar coverage: in-window symbol-days | with bars | share; catalyst events (P) '
            'with P_ref | with an entry bar (structure only)')
        for y in sorted(nw.year.unique()):
            n_sd = int((sd.year == y).sum())
            keys_y = {(r.symbol, r.day) for r in sd[sd.year == y].itertuples()}
            nb = have[y]
            log(f'  {y}: {n_sd:>6} | {nb:>6} | {nb / max(n_sd, 1):5.1%} ; catalyst P events '
                f'{struct[(y, "catalyst", "P", "event")]:>5} | ref {struct[(y, "catalyst", "P", "ref")]:>5} | '
                f'tradable {struct[(y, "catalyst", "P", "tradable")]:>5}')
            del keys_y
    conn.close()


# ── evaluate ─────────────────────────────────────────────────────────────────

def add_nets(T):
    cost = np.where(T.tier == 'S', COST_SMALL, COST)
    costhi = np.where(T.tier == 'S', COST_SMALL, COST_HI)
    for g in ('g10', 'g30', 'g60', 'gc', 'fg30'):
        T['n_' + g] = T[g] - 2 * cost
    T['r'] = T['g30'] - 2 * cost
    T['rhi'] = T['g30'] - 2 * costhi
    T['abs_r'] = T.r_react.abs()
    return T


def sel(T, tier='P', kind='catalyst', thr=THR):
    m = (T.tier == tier) & (T.kind == kind) & (T.r_react.abs() >= thr - THR_EPS) & T.g30.notna()
    return T[m]


def summ(label, T, col='r'):
    if T is None or T.empty or T[col].dropna().empty:
        return f'{label:<52} (no trades)'
    g = T.dropna(subset=[col])
    return lg.fmt(label, lg.dci(g[col].values, g.day.values))


def primary_block(P, years):
    log('\n######## PRE-REGISTERED: primary tier, catalyst headlines 10:00-14:59:59, |reaction| >= 1.0%, '
        'enter t0+2..t0+6, 30-minute hold ########')
    if P.empty:
        log('no trades -> VERDICT: FAIL')
        return
    s = lg.dci(P.r.values, P.day.values)
    log(lg.fmt('net return @0.15%/side (primary)', s))
    log(lg.fmt('net return @0.30%/side', lg.dci(P.rhi.values, P.day.values)))
    log(f'gross signed mean (no costs): {(P.r.mean() + 2 * COST) * 100:+.3f}%')
    yr = {}
    for y in years:
        g = P[P.year == y]
        yr[y] = g.r.mean() if len(g) else np.nan
        log(f'  {y}: trades {len(g):>5}  mean {yr[y] * 100:+7.3f}%  pos {np.mean(g.r > 0) if len(g) else 0:4.0%}')
    npos = sum(1 for v in yr.values() if v > 0)
    halves = [P[(P.year >= a) & (P.year <= b)].r for a, b in HALVES]
    hm = [h.mean() if len(h) else float('nan') for h in halves]
    trimmed = P[P.r <= P.r.quantile(0.99)].r.mean()
    n, mean, _, _, lo, _, _ = s
    a_ = n >= MIN_TRADES
    b_ = mean > 0 and lo > 0
    c_ = all(h > 0 for h in hm)
    d_ = npos >= MIN_YEARS_POS
    e_ = P.rhi.mean() > 0
    f_ = trimmed > 0
    tag = lambda ok: 'PASS' if ok else 'FAIL'  # noqa: E731
    log(f'\nCRITERIA (a) >= {MIN_TRADES} trades: {n} -> {tag(a_)}')
    log(f'         (b) mean > 0 and CI lower > 0: {mean * 100:+.3f}% / {lo * 100:+.3f}% -> {tag(b_)}')
    log(f'         (c) mean > 0 in 2016-2020 and 2021-2026: {hm[0] * 100:+.3f}% / {hm[1] * 100:+.3f}% -> {tag(c_)}')
    log(f'         (d) positive mean in >= {MIN_YEARS_POS} of {len(years)} years: {npos} -> {tag(d_)}')
    log(f'         (e) mean > 0 at 0.30%/side: {P.rhi.mean() * 100:+.3f}% -> {tag(e_)}')
    log(f'         (f) mean > 0 after dropping best 1% of trades: {trimmed * 100:+.3f}% -> {tag(f_)}')
    log(f'VERDICT: {"PASS" if all((a_, b_, c_, d_, e_, f_)) else "FAIL"}')


def report_block(T, P, years):
    log('\n######## REPORT-ONLY (never used to decide), @0.15%/side unless stated ########')
    log('-- holds (primary events, entry unchanged)')
    for lab, col in (('10 min hold', 'n_g10'), ('30 min hold (primary)', 'n_g30'), ('60 min hold', 'n_g60'),
                     ('hold to 15:59', 'n_gc')):
        log(summ(lab, P, col))
    log('-- reaction threshold')
    for th in (0.005, 0.01, 0.02):
        log(summ(f'|reaction| >= {th:.1%}', sel(T, thr=th)))
    log('-- reaction-size terciles (primary trades, by |r_react|)')
    if len(P) >= 3:
        q = pd.qcut(P.abs_r, 3, labels=['small', 'middle', 'large'], duplicates='drop')
        for lab in q.cat.categories:
            g = P[q == lab]
            log(summ(f'tercile {lab} (|r| {g.abs_r.min():.2%}..{g.abs_r.max():.2%})', g))
    log('-- direction')
    log(summ('long (up reaction)', P[P.r_react > 0]))
    log(summ('short (down reaction)', P[P.r_react < 0]))
    log('-- hour of day of the headline (ET)')
    for h in range(10, 15):
        log(summ(f'headline hour {h}:00-{h}:59', P[P.hour == h]))
    log('-- per-year means (primary)')
    for y in years:
        g = P[P.year == y]
        log(f'  {y}: n={len(g):>5} mean {g.r.mean() * 100 if len(g) else float("nan"):+7.3f}%')
    log('-- faster entry (open of the t0+1 bar; reaction from bars <= t0; 30 min hold)')
    F = T[(T.tier == 'P') & (T.kind == 'catalyst') & T.fr.notna() & (T.fr.abs() >= THR - THR_EPS) & T.fg30.notna()]
    log(summ('fast entry, net @0.15%', F, 'n_fg30'))
    log(f'  fast entry gross signed mean: {(F.n_fg30.mean() + 2 * COST) * 100 if len(F) else float("nan"):+.3f}% '
        f'(n={len(F)})')
    log('-- gross signed return, no costs (primary)')
    if len(P):
        log(f'  mean {(P.n_g30.mean() + 2 * COST) * 100:+.3f}%  median {(P.n_g30.median() + 2 * COST) * 100:+.3f}%  '
            f'(positive = drift in the direction of the reaction, negative = reversal)')
    log('-- placebo: first article of the day is a non-catalyst (roundup / reaction), same rule, primary tier')
    PL = sel(T, 'P', 'placebo')
    log(summ('placebo net @0.15%', PL))
    if len(PL):
        log(f'  placebo gross signed mean {(PL.r.mean() + 2 * COST) * 100:+.3f}%')
    log('-- small-cap tier (catalyst events, cost 0.5%/side)')
    S = sel(T, 'S', 'catalyst')
    log(summ('small tier net @0.5%', S))
    if len(S):
        log(f'  small tier gross signed mean {(S.r.mean() + 2 * COST_SMALL) * 100:+.3f}%')
    log(summ('small tier placebo net @0.5%', sel(T, 'S', 'placebo')))


def evaluate(args):
    np.random.seed(BOOT_SEED)
    lg.RNG = np.random.default_rng(BOOT_SEED)      # dci() draws from lg.RNG: fixed seed
    start, end = START_DEFAULT, END_DEFAULT
    conn = psycopg2.connect(DSN)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    md, mn, mm = completeness(conn, get_universe(), start, end)
    if (md or mn or mm) and not args.allow_incomplete:
        raise SystemExit(f'collection incomplete (daily batches {len(md)}, news days {len(mn)}, minute days '
                         f'{len(mm)}); finish `collect` first. Nothing was evaluated.')
    years = list(range(start.year, end.year + 1))
    nw = load_news(conn, start, end)
    evs = events_from_news(nw)
    log(f'SEALED {start}..{end}\nevents: catalyst P {sum(1 for e in evs if e[3] == "catalyst" and e[2] == "P")} | '
        f'catalyst S {sum(1 for e in evs if e[3] == "catalyst" and e[2] == "S")} | '
        f'placebo P {sum(1 for e in evs if e[3] == "placebo" and e[2] == "P")} | '
        f'placebo S {sum(1 for e in evs if e[3] == "placebo" and e[2] == "S")}')
    T = add_nets(build_trades(conn, evs, start, end))
    conn.close()
    P = sel(T)
    log(f'events with minute bars and a usable P_ref: {len(T)} | primary trades (|reaction| >= 1%, entry bar found): '
        f'{len(P)}')
    primary_block(P, years)
    report_block(T, P, years)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'evaluate_{ts}.txt')
    open(path, 'w', encoding='utf-8').write('\n'.join(_BUF) + '\n')
    log(f'\nDONE evaluate (output saved to {path})')


# ── selftest ─────────────────────────────────────────────────────────────────

def _bars(spec):
    """spec: {minute: (open, close)} -> (m, o, h, l, c) arrays; high/low bracket open/close."""
    ms = sorted(spec)
    m = np.array(ms)
    o = np.array([spec[k][0] for k in ms], float)
    c = np.array([spec[k][1] for k in ms], float)
    return m, o, np.maximum(o, c), np.minimum(o, c), c


def selftest():
    n_ok = 0

    def ok(cond, msg):
        nonlocal n_ok
        if not cond:
            raise AssertionError(msg)
        n_ok += 1

    def approx(a, b):
        return abs(a - b) < 1e-9

    t0 = 600          # 10:00
    flat = {m: (100.0, 100.0) for m in range(585, 700)}

    # 1. long: ref = close(t0-1) = 100; react bar t0+1 closes 102; entry = open(t0+2); exit = close(entry+29)
    s = dict(flat)
    s[600] = (100.0, 101.0)
    s[601] = (101.0, 102.0)
    s[602] = (103.0, 103.5)
    s[631] = (104.0, 105.0)       # entry 602 + 29 = 631
    s[632] = (105.0, 110.0)       # must NOT be used
    ev = simulate_event(_bars(s), t0)
    ok(approx(ev['r'], 0.02) and ev['entry'] == 103.0 and ev['x30'] == 105.0 and ev['emin'] == 602, 'long basic')
    ok(approx(signed_gross(ev['r'], ev['entry'], ev['x30']), 105 / 103 - 1), 'long sign')
    ok(ev['x10'] == flat[611][1] and ev['x60'] == 100.0, 'hold 10 / 60 exits')
    ok(approx(net(0.02, COST), 0.02 - 0.003), 'cost applied twice')

    # 2. price after t0+1 does not change the reaction
    s2 = dict(s)
    s2[602] = (103.0, 150.0)
    s2[603] = (150.0, 150.0)
    ok(approx(simulate_event(_bars(s2), t0)['r'], 0.02), 'reaction uses only bars starting <= t0+1')

    # 3. short: reaction down -> short, return = -(exit/entry-1)
    d = dict(flat)
    d[601] = (100.0, 98.0)
    d[602] = (97.0, 97.0)
    d[631] = (96.0, 95.0)
    ev = simulate_event(_bars(d), t0)
    ok(approx(ev['r'], -0.02) and ev['entry'] == 97.0 and ev['x30'] == 95.0, 'short basic')
    ok(approx(signed_gross(ev['r'], ev['entry'], ev['x30']), -(95 / 97 - 1)), 'short sign')

    # 4. threshold 1.0% edge: exactly +1.0% trades, +0.99% does not
    e1 = dict(flat)
    e1[601] = (100.0, 101.0)
    ok(passes(simulate_event(_bars(e1), t0)['r']), 'exactly 1.0% passes')
    e2 = dict(flat)
    e2[601] = (100.0, 100.99)
    ok(not passes(simulate_event(_bars(e2), t0)['r']), '0.99% does not pass')

    # 5. missing t0-1 bar: P_ref = last earlier bar (t0-2 close)
    mm = dict(s)
    del mm[599]
    mm[598] = (99.0, 99.5)
    ev = simulate_event(_bars(mm), t0)
    ok(approx(ev['r'], 102 / 99.5 - 1), 'missing t0-1 bar -> uses t0-2 close')

    # 6. P_ref exactly t0-10 allowed; older than 10 min -> no trade at all
    at10 = {590: (100.0, 100.0), 601: (100.0, 102.0), 602: (102.0, 102.0)}
    ok(simulate_event(_bars(at10), t0) is not None and approx(simulate_event(_bars(at10), t0)['r'], 0.02),
       'bar at t0-10 allowed')
    old = {589: (100.0, 100.0), 601: (100.0, 102.0), 602: (102.0, 102.0)}
    ok(simulate_event(_bars(old), t0) is None, 'P_ref older than 10 min -> no trade')
    ok(simulate_event(_bars({601: (100.0, 102.0), 602: (102.0, 102.0)}), t0) is None, 'no bar before t0 -> no trade')

    # 7. no bar in t0+2..t0+6 -> no trade; bar at t0+7 does not count; t0+6 does
    ne = {m: v for m, v in s.items() if not (602 <= m <= 606)}
    ev = simulate_event(_bars(ne), t0)
    ok(ev is not None and ev['entry'] != ev['entry'], 'no entry bar t0+2..t0+6 -> NaN entry')
    ne[606] = (104.0, 104.0)
    ev = simulate_event(_bars(ne), t0)
    ok(ev['entry'] == 104.0 and ev['emin'] == 606, 'entry may be t0+6')
    ne2 = {m: v for m, v in s.items() if not (602 <= m <= 606)}
    ne2[607] = (104.0, 104.0)
    ok(simulate_event(_bars(ne2), t0)['entry'] != simulate_event(_bars(ne2), t0)['entry'], 'bar at t0+7 is too late')

    # 8. no reaction bars at t0..t0+1: P_react is P_ref -> r = 0 -> never a trade
    nr = {m: (100.0, 100.0) for m in range(585, 600)}
    nr[602] = (110.0, 110.0)
    ev = simulate_event(_bars(nr), t0)
    ok(ev is not None and ev['r'] == 0 and not passes(ev['r']), 'no reaction bar -> r=0 -> no trade')

    # 9. exit cut at 15:59: event 14:58, entry 15:00 (900), 60-min hold would end after 15:59
    t1 = 14 * 60 + 58
    late = {m: (100.0, 100.0) for m in range(t1 - 12, 960)}
    late[t1 + 1] = (100.0, 102.0)
    late[t1 + 2] = (102.0, 102.0)
    late[959] = (103.0, 107.0)
    ev = simulate_event(_bars(late), t1)
    ok(ev['entry'] == 102.0 and ev['xc'] == 107.0 and ev['x60'] == 107.0, 'exit cut at 15:59 for 60-min and close holds')
    ok(ev['x30'] == 100.0, '30-min hold ends before the cut')
    # last allowed bar earlier than the limit: use the last existing bar <= limit
    gap = {m: v for m, v in late.items() if m <= 910}
    ev = simulate_event(_bars(gap), t1)
    ok(ev['xc'] == 100.0, 'exit = last existing bar')

    # 10. entry bar is the only bar left: exit = entry bar close (trade still happens)
    one = {599: (100.0, 100.0), 601: (100.0, 102.0), 602: (102.0, 103.0)}
    ev = simulate_event(_bars(one), t0)
    ok(ev['entry'] == 102.0 and ev['x30'] == 103.0, 'entry bar doubles as exit bar')

    # 11. fast entry: needs bar exactly at t0+1; reaction from bars <= t0
    f = dict(flat)
    f[600] = (100.0, 102.0)
    f[601] = (102.0, 103.0)
    f[602] = (103.0, 103.0)
    ev = simulate_event(_bars(f), t0)
    ok(approx(ev['fr'], 0.02) and ev['fentry'] == 102.0, 'fast variant uses open of t0+1 and reaction from t0 bar')
    nf = {m: v for m, v in f.items() if m != 601}
    ok(simulate_event(_bars(nf), t0)['fentry'] != simulate_event(_bars(nf), t0)['fentry'], 'fast: no t0+1 bar -> none')

    # 12. freshness / window (sod in seconds; key negative = prior day)
    C, R, X = 'catalyst', 'roundup', 'reaction'
    sod = lambda h, m=0, s_=0: h * 3600 + m * 60 + s_  # noqa: E731
    pe = lambda arts: pick_events([(k, i, t, sd) for i, (k, t, sd) in enumerate(arts)])  # noqa: E731
    ok(pe([(sod(10), C, sod(10))]) == (36000, None), 'created_at exactly 10:00:00 included')
    ok(pe([(sod(14, 59, 59), C, sod(14, 59, 59))]) == (53999, None), '14:59:59 included')
    ok(pe([(sod(14, 59, 59) + .5, C, sod(14, 59, 59) + .5)]) == (53999.5, None), '14:59:59.5 included')
    ok(pe([(sod(15), C, sod(15))]) == (None, None), '15:00:00 excluded')
    ok(pe([(sod(9, 59, 59), C, sod(9, 59, 59))]) == (None, None), '09:59:59 excluded')
    ok(pe([(sod(11), C, sod(11)), (sod(12), C, sod(12))]) == (sod(11), None), 'second catalyst is not an event')
    ok(pe([(sod(8), C, sod(8)), (sod(11), C, sod(11))]) == (None, None), 'morning catalyst blocks a later one')
    ok(pe([(-3600, C, sod(17)), (sod(11), C, sod(11))]) == (None, None), 'prior-evening catalyst blocks')
    ok(pe([(sod(8), R, sod(8)), (sod(11), C, sod(11))]) == (sod(11), None), 'roundup does not block freshness')
    ok(pe([(sod(8), X, sod(8)), (sod(11), C, sod(11))]) == (sod(11), None), 'reaction piece does not block')
    ok(pe([(sod(11), C, sod(11)), (sod(11), C, sod(11))]) == (sod(11), None), 'same-second ties: one event')
    ok(pe([(sod(11), R, sod(11))]) == (None, sod(11)), 'placebo: first article non-catalyst')
    ok(pe([(sod(11), R, sod(11)), (sod(12), C, sod(12))]) == (sod(12), None), 'catalyst day is never a placebo day')
    ok(pe([(sod(8), R, sod(8)), (sod(11), R, sod(11))]) == (None, None), 'placebo must be the first article')
    ok(pe([(sod(15), R, sod(15))]) == (None, None), 'placebo 15:00:00 excluded')
    ok(pe([]) == (None, None), 'empty')

    # 13. tiers
    t = tier_of([10, 10, 9.99, 500, 501, 0.99, 5, 50, 30], [50e6, 49.9e6, 2e6, 50e6, 100e6, 5e6, 1.9e6, 2e6, 10e6])
    ok(list(t) == ['P', 'S', 'S', 'P', '', '', '', 'S', 'S'], f'tiers {list(t)}')
    ok(tier_of([np.nan], [1e9])[0] == '', 'NaN prior close -> no tier')

    # 14. look-ahead in screen_daily: ADV and prior close exclude the day itself
    days = np.array([date(2024, 1, 1) + timedelta(days=i) for i in range(30)])
    c = np.full(30, 20.0)
    v = np.full(30, 3e6)         # $60M/day
    v[29] = 1e12                 # huge volume on the last day only: must NOT count towards its own ADV
    c[29] = 400.0
    rows = screen_daily(days, c, v, days[0], days[-1])
    last = [r for r in rows if r[0] == days[29]][0]
    ok(last[1] == 'P' and last[2] == 20.0 and abs(last[3] - 60e6) < 1, 'prior close / ADV strictly before the day')
    ok(not [r for r in rows if r[0] < days[15]], 'fewer than 15 prior bars -> not a candidate')
    print(f'SELFTEST OK ({n_ok} checks)')


def main():
    p = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('collect', 'check'):
        s = sub.add_parser(name)
        s.add_argument('--start', default=START_DEFAULT.isoformat())
        s.add_argument('--end', default=END_DEFAULT.isoformat())
        if name == 'collect':
            s.add_argument('--accept-empty', action='store_true')
    e = sub.add_parser('evaluate')
    e.add_argument('--allow-incomplete', action='store_true')
    sub.add_parser('selftest')
    args = p.parse_args()
    if args.cmd == 'selftest':
        selftest()
    else:
        {'collect': collect, 'check': check, 'evaluate': evaluate}[args.cmd](args)


if __name__ == '__main__':
    main()
