"""Stocks-in-Play 5-minute opening-range breakout, with honest costs and a post-publication window.
PRE-REGISTERED in docs/PREREG_2026_10_STOCKS_IN_PLAY_ORB.md (committed before any data was pulled).
One look at the results; nothing here may change after `evaluate` has been run.

Replicates the rule summarized from Zarattini, Barbon & Aziz (2024): each day, among liquid US stocks
(open > $5, 14-day average volume >= 1M shares, 14-day ATR > $0.50), take the 20 with the highest
opening-range relative volume (first 5 minutes vs the prior 14 days' first 5 minutes, >= 1.0x). Trade the
breakout of the 5-minute range in the direction of the first 5-minute candle, stop at 10% of ATR, exit at
the close. Costs 0.15%/side primary, 0.30%/side robustness.

Stages (each caches in local TimescaleDB tables orb_* and resumes):
  python research/analysis/scripts/stocks_in_play_orb_test.py collect    daily bars -> eligibility,
                                                                         opening ranges, selection, full-day bars
  python research/analysis/scripts/stocks_in_play_orb_test.py evaluate   the one look
"""
import os
import pickle
import sys
import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import TimeFrame, _client, _fetch, _insert  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from ross_premarket_test import DSN  # noqa: E402

ET = pytz.timezone('America/New_York')
UNIVERSE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'liquid_gap', 'universe.pkl'))
START, END, POST = date(2016, 1, 4), date(2026, 10, 16), date(2024, 1, 2)
MIN_OPEN, MIN_ADV, MIN_ATR = 5.0, 1_000_000, 0.50
LOOSE_OPEN, LOOSE_ADV = 3.0, 500_000          # baseline days for relative volume
GAP_LO, GAP_HI = -0.40, 0.60                  # split-artifact guard (raw prices)
TOP_N, MIN_RVOL, STOP_ATR = 20, 1.0, 0.10
COST, COST_HI, COMMISSION = 0.0015, 0.003, 0.0035
OPEN_MIN, LAST_ENTRY, LAST_EXIT = 570, 955, 959
SLEEP, BOOT = 0.3, 3000
RNG = np.random.default_rng(20261021)
DDL = """
CREATE TABLE IF NOT EXISTS orb_eligible (symbol varchar(10), day date, open float8, prior_close float8,
    atr14 float8, adv14 float8, strict boolean, PRIMARY KEY (day, symbol));
CREATE TABLE IF NOT EXISTS orb_or5 (symbol varchar(10), day date, o float8, h float8, l float8, c float8,
    v float8, n int, PRIMARY KEY (day, symbol));
CREATE TABLE IF NOT EXISTS orb_selected (day date, symbol varchar(10), rvol float8, rnk int, dir int,
    or_h float8, or_l float8, atr14 float8, PRIMARY KEY (day, symbol));
CREATE TABLE IF NOT EXISTS orb_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL);
CREATE TABLE IF NOT EXISTS orb_done (kind text, key text, PRIMARY KEY (kind, key));
"""


def log(*a):
    print(*a, flush=True)


def _done(conn, kind):
    with conn.cursor() as cur:
        cur.execute('SELECT key FROM orb_done WHERE kind = %s', (kind,))
        return {r[0] for r in cur.fetchall()}


def _mark(conn, kind, key):
    with conn.cursor() as cur:
        cur.execute('INSERT INTO orb_done VALUES (%s, %s) ON CONFLICT DO NOTHING', (kind, key))
    conn.commit()


# ── collection ────────────────────────────────────────────────────────────────

def daily(conn, client, syms):
    done = _done(conn, 'daily')
    start = ET.localize(datetime(2015, 11, 15))
    end = ET.localize(datetime(END.year, END.month, END.day, 23))
    for i in range(0, len(syms), 200):
        if str(i) in done:
            continue
        data = _fetch(client, syms[i:i + 200], TimeFrame.Day, start, end)
        rows = []
        for sym, bars in data.items():
            if len(bars) < 20:
                continue
            d = np.array([b.timestamp.astimezone(ET).date() for b in bars])
            o = np.array([b.open for b in bars], dtype=float)
            h = np.array([b.high for b in bars], dtype=float)
            l = np.array([b.low for b in bars], dtype=float)
            c = np.array([b.close for b in bars], dtype=float)
            v = np.array([b.volume for b in bars], dtype=float)
            pc = np.r_[np.nan, c[:-1]]
            tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
            atr = pd.Series(np.r_[np.nan, tr[:-1]]).rolling(14, min_periods=14).mean().values
            adv = pd.Series(np.r_[np.nan, v[:-1]]).rolling(14, min_periods=14).mean().values
            with np.errstate(invalid='ignore', divide='ignore'):
                gap = o / pc - 1
                loose = (d >= START) & (d <= END) & (o >= LOOSE_OPEN) & (adv >= LOOSE_ADV) \
                    & (gap >= GAP_LO) & (gap <= GAP_HI)
                strict = loose & (o > MIN_OPEN) & (adv >= MIN_ADV) & (atr > MIN_ATR)
            for k in np.where(loose)[0]:
                rows.append((sym, d[k], float(o[k]), float(pc[k]), float(atr[k]), float(adv[k]),
                             bool(strict[k])))
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO orb_eligible VALUES %s ON CONFLICT DO NOTHING',
                                               rows, page_size=5000)
        conn.commit()
        _mark(conn, 'daily', str(i))
        log(f'  daily {min(i + 200, len(syms))}/{len(syms)} symbols (+{len(rows)} eligible rows)')


def opening_ranges(conn, client):
    with conn.cursor() as cur:
        cur.execute('SELECT DISTINCT day FROM orb_eligible ORDER BY day')
        days = [r[0] for r in cur.fetchall()]
    done = _done(conn, 'or5')
    todo = [d for d in days if d.isoformat() not in done]
    log(f'opening ranges: {len(days)} days, {len(todo)} to fetch')
    t0 = time.time()
    for i, d in enumerate(todo, 1):
        with conn.cursor() as cur:
            cur.execute('SELECT symbol FROM orb_eligible WHERE day = %s', (d,))
            syms = sorted(r[0] for r in cur.fetchall())
        s = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
        e = ET.localize(datetime(d.year, d.month, d.day, 9, 35))
        rows, failed = [], False
        for j in range(0, len(syms), 400):
            data = _fetch(client, syms[j:j + 400], TimeFrame.Minute, s, e)
            time.sleep(SLEEP)
            failed |= not data  # _fetch returns {} when it gives up; leave the day unmarked so a rerun retries it
            for sym, bars in data.items():
                if len(bars) >= 3:
                    bars = sorted(bars, key=lambda b: b.timestamp)
                    rows.append((sym, d, bars[0].open, max(b.high for b in bars), min(b.low for b in bars),
                                 bars[-1].close, float(sum(b.volume for b in bars)), len(bars)))
        with conn.cursor() as cur:
            if rows:
                psycopg2.extras.execute_values(cur, 'INSERT INTO orb_or5 VALUES %s ON CONFLICT DO NOTHING', rows)
        conn.commit()
        if not failed:
            _mark(conn, 'or5', d.isoformat())
        if i % 100 == 0 or i == len(todo):
            log(f'  or5 {i}/{len(todo)} days ({time.time() - t0:.0f}s)')


def select(conn):
    """Top 20 strict-eligible stocks by opening-range relative volume (vs the prior 14 OR days), rvol >= 1."""
    with conn.cursor() as cur:
        cur.execute('SET timescaledb.enable_vectorized_aggregation = off')
        cur.execute('TRUNCATE orb_selected')
        cur.execute(f"""
            WITH r AS (
                SELECT symbol, day, o, h, l, c, v,
                       AVG(v) OVER w AS base, COUNT(v) OVER w AS nbase
                FROM orb_or5
                WINDOW w AS (PARTITION BY symbol ORDER BY day ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING)
            ), s AS (
                SELECT r.day, r.symbol, r.v / NULLIF(r.base, 0) AS rvol,
                       CASE WHEN r.c > r.o THEN 1 WHEN r.c < r.o THEN -1 ELSE 0 END AS dir,
                       r.h AS or_h, r.l AS or_l, e.atr14
                FROM r JOIN orb_eligible e ON e.day = r.day AND e.symbol = r.symbol
                WHERE e.strict AND r.nbase >= 10 AND r.base > 0
            ), k AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY day ORDER BY rvol DESC) AS rnk
                FROM s WHERE rvol >= {MIN_RVOL}
            )
            INSERT INTO orb_selected SELECT day, symbol, rvol, rnk, dir, or_h, or_l, atr14
            FROM k WHERE rnk <= {TOP_N}""")
        cur.execute('SELECT count(*), count(DISTINCT day) FROM orb_selected')
        n, nd = cur.fetchone()
    conn.commit()
    log(f'selected: {n} stock-days over {nd} days')


def full_day_bars(conn, client):
    with conn.cursor() as cur:
        cur.execute('SELECT day, array_agg(symbol) FROM orb_selected GROUP BY day ORDER BY day')
        groups = cur.fetchall()
    done = _done(conn, 'bars')
    todo = [(d, s) for d, s in groups if d.isoformat() not in done]
    log(f'full-day bars: {len(groups)} days, {len(todo)} to fetch')
    for i, (d, syms) in enumerate(todo, 1):
        s = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
        e = ET.localize(datetime(d.year, d.month, d.day, 16, 0))
        _insert(conn, 'orb_bars_1m', _fetch(client, sorted(syms), TimeFrame.Minute, s, e))
        conn.commit()
        _mark(conn, 'bars', d.isoformat())
        time.sleep(SLEEP)
        if i % 200 == 0 or i == len(todo):
            log(f'  bars {i}/{len(todo)} days')


def collect():
    conn = psycopg2.connect(DSN)
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    client = _client()
    syms = pickle.load(open(UNIVERSE, 'rb'))
    log(f'universe: {len(syms)} symbols (from liquid_gap_orb_test)')
    daily(conn, client, syms)
    opening_ranges(conn, client)
    select(conn)
    full_day_bars(conn, client)
    conn.close()
    log('DONE collect')


# ── evaluation ────────────────────────────────────────────────────────────────

def trade(m, o, h, l, c, sel):
    dirn = sel.dir
    if dirn == 0:
        return None
    risk = STOP_ATR * sel.atr14
    if dirn > 0:
        lvl = sel.or_h + 0.01
        trig = np.where((m >= OPEN_MIN + 5) & (m <= LAST_ENTRY) & (h >= lvl))[0]
    else:
        lvl = sel.or_l - 0.01
        trig = np.where((m >= OPEN_MIN + 5) & (m <= LAST_ENTRY) & (l <= lvl))[0]
    if not trig.size:
        return None
    k = int(trig[0])
    entry = max(o[k], lvl) if dirn > 0 else min(o[k], lvl)
    stop = entry - risk if dirn > 0 else entry + risk
    n, kind, fill = len(m), 'close', None
    for j in range(k + 1, n):
        if m[j] > LAST_EXIT:
            break
        if (dirn > 0 and o[j] <= stop) or (dirn < 0 and o[j] >= stop):
            kind, fill = 'gap', o[j]
            break
        if (dirn > 0 and l[j] <= stop) or (dirn < 0 and h[j] >= stop):
            nxt = o[j + 1] if j + 1 < n else c[j]
            kind, fill = 'stop', (min(stop, nxt) if dirn > 0 else max(stop, nxt))
            break
    if fill is None:
        last = np.where(m <= LAST_EXIT)[0]
        fill = c[last[-1]]
    return {'dir': dirn, 'entry': entry, 'exit': fill, 'risk': risk, 'kind': kind}


def net_r(t, cost):
    """Net R per trade with cost per side as a fraction of price (array-friendly)."""
    gross = (t.exit - t.entry) * t.dir
    return (gross - cost * (t.entry + t.exit)) / t.risk


def net_pct(t, cost):
    gross = (t.exit - t.entry) * t.dir
    return (gross - cost * (t.entry + t.exit)) / t.entry


def dci(v, days):
    s = pd.DataFrame({'v': v, 'd': days}).dropna()
    if len(s) < 10:
        return None
    g = s.groupby('d').v.agg(['sum', 'count'])
    su, n = g['sum'].values, g['count'].values
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    b = su[idx].sum(1) / n[idx].sum(1)
    return len(s), s.v.mean(), np.median(s.v), (s.v > 0).mean(), np.percentile(b, 2.5), np.percentile(b, 97.5), len(g)


def fmt(label, s, unit='R', k=1):
    if s is None:
        return f'{label:<50} (n<10)'
    n, mean, med, pos, lo, hi, nd = s
    return (f'{label:<50} n={n:>6} d={nd:>4}  mean {mean*k:+7.3f}{unit}  median {med*k:+7.3f}{unit}  '
            f'pos {pos:4.0%}  CI [{lo*k:+.3f}, {hi*k:+.3f}]')


def evaluate():
    conn = psycopg2.connect(DSN)
    sel = pd.read_sql('SELECT * FROM orb_selected ORDER BY day, rnk', conn)
    rows = []
    for d, g in sel.groupby('day'):
        b = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et, open, high, low, close
                           FROM orb_bars_1m WHERE time >= %s AND time < %s""", conn,
                        params=(datetime(d.year, d.month, d.day), datetime(d.year, d.month, d.day, 23, 59)))
        b['m'] = b.et.dt.hour * 60 + b.et.dt.minute
        bars = {s: x.sort_values('et') for s, x in b.groupby('symbol')}
        for r in g.itertuples():
            x = bars.get(r.symbol)
            if x is None or len(x) < 10:
                continue
            t = trade(x.m.values, x.open.values, x.high.values, x.low.values, x.close.values, r)
            if t:
                rows.append({'day': d, 'year': d.year, 'symbol': r.symbol, 'rnk': r.rnk, **t})
    conn.close()
    T = pd.DataFrame(rows)
    T['R'] = net_r(T, COST)
    T['Rhi'] = net_r(T, COST_HI)
    T['pct'] = net_pct(T, COST)
    T['Rpaper'] = ((T.exit - T.entry) * T.dir - 2 * COMMISSION) / T.risk
    log(f'selected stock-days {len(sel)} | trades {len(T)} over {T.day.nunique()} days')

    log('\n######## PRE-REGISTERED: top-20 stocks in play, 5-min ORB, stop 10% ATR, exit at close ########')
    s = dci(T.R.values, T.day.values)
    post = T[T.day >= POST]
    sp = dci(post.R.values, post.day.values)
    log(fmt('net R @0.15%/side, full period', s))
    log(fmt('net R @0.15%/side, post-publication 2024-01..2026-10', sp))
    log(fmt('net R @0.30%/side, full period', dci(T.Rhi.values, T.day.values)))
    log(fmt('net % @0.15%/side, full period', dci(T.pct.values, T.day.values), unit='%', k=100))
    log('exits: ' + ', '.join(f'{k} {v:.0%}' for k, v in T.kind.value_counts(normalize=True).items()))
    trimmed = T[T.R <= T.R.quantile(0.99)].R.mean()
    n, mean, _, _, lo, _, _ = s
    a_, b_ = n >= 1000, (mean > 0 and lo > 0)
    c_, d_, e_ = post.R.mean() > 0, T.Rhi.mean() > 0, trimmed > 0
    log(f'\nCRITERIA (a) >=1000 trades: {n} -> {"PASS" if a_ else "FAIL"}')
    log(f'         (b) mean R>0, CI lower>0 (full): {mean:+.3f}R / {lo:+.3f}R -> {"PASS" if b_ else "FAIL"}')
    log(f'         (c) mean R>0 post-publication: {post.R.mean():+.3f}R -> {"PASS" if c_ else "FAIL"}')
    log(f'         (d) mean R>0 at 0.30%/side: {T.Rhi.mean():+.3f}R -> {"PASS" if d_ else "FAIL"}')
    log(f'         (e) mean R>0 without best 1%: {trimmed:+.3f}R -> {"PASS" if e_ else "FAIL"}')
    log(f'VERDICT: {"PASS" if all((a_, b_, c_, d_, e_)) else "FAIL"}')

    log('\n######## REPORT-ONLY (never used to decide) ########')
    log(fmt("paper's cost assumption ($0.0035/share commission only)", dci(T.Rpaper.values, T.day.values)))
    log(fmt('gross (no costs)', dci(((T.exit - T.entry) * T.dir / T.risk).values, T.day.values)))
    for lab, x in (('long only', T[T.dir > 0]), ('short only', T[T.dir < 0]), ('top 10 only', T[T.rnk <= 10])):
        log(fmt(f'{lab} @0.15%/side', dci(x.R.values, x.day.values)))
    for y, x in T.groupby('year'):
        log(f'  {y}: trades {len(x):>5}  mean {x.R.mean():+.3f}R  pos {np.mean(x.R > 0):4.0%}  '
            f'(paper-cost {x.Rpaper.mean():+.3f}R)')
    T.to_csv(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'orb_sip_trades.csv')),
             index=False)
    log('\nDONE evaluate')


if __name__ == '__main__':
    {'collect': collect, 'evaluate': evaluate}[sys.argv[1]]()
