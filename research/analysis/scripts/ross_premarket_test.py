"""Premarket test: is Ross Cameron's edge in the 7:00-9:30 premarket window?

Follow-up to ross_oracle_entry_test.py / ross_selection_test.py, which only covered 9:30+.
Roughly 40-50% of Ross's trades with a stated time are premarket, and none of our strategies
trade there.

Pieces (each stage caches to research/analysis/outputs/premarket/, re-runs resume):

1. UNIVERSE + PRIOR CLOSE (hindsight-free). Ticker list = Alpaca assets (active + inactive)
   ∪ every symbol in our DB ∪ Ross's ledger symbols. Daily bars give each symbol's prior-day
   close and volume. Eligible that morning: prior close $1-$20, prior-day volume >= 50k.
2. PREMARKET SCANNER rebuilt from 15-minute bars 04:00-09:30, using only data up to each
   checkpoint: at the end of each 15-min bar from 07:00 to 09:30 a symbol is flagged the
   FIRST time it is >= +10% vs prior close, priced $1-$20, with >= 100k shares traded since
   04:00. Flag time = that bar's end.
3. Minute bars 04:00-12:00 for every scanner hit (same Alpaca SIP feed as Ross's bars).

Tests (entry = open of the next minute, exit = close less 0.3% slippage):
  A. Scanner as a strategy: buy every hit at its flag time. Is a dumb premarket scanner +EV?
  B. Ross's premarket entries, one bar late (estimated time = first touch of his price at/after
     07:00 on a >=10k-share bar, before 09:30; day = nearest weekday on/before upload).
  C. Selection, paired by day: random entry in [Ross pick time, 09:30) on Ross's stock vs. on
     scanner hits already flagged by that time. Does Ross pick better premarket stocks?

Usage:  python research/analysis/scripts/ross_premarket_test.py
"""
import os
import pickle
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, TimeFrame, _client, _fetch, _insert  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from ross_oracle_entry_test import first_price  # noqa: E402
from alpaca.data.timeframe import TimeFrameUnit  # noqa: E402

DSN = os.environ.get('STOCKDATA_DSN', 'postgresql://postgres:changeme123@localhost:5432/stockdata')
CACHE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'premarket'))
SLIP = 0.003
HOLDS = [1, 5, 10, 30]
PM_START, OPEN = 7 * 60, 9 * 60 + 30
MIN_GAP, MIN_PM_VOL, MIN_PRIOR_VOL = 0.10, 100_000, 50_000
RNG = np.random.default_rng(20261008)
BATCH = 200


def log(*a):
    print(*a, flush=True)


def cached(name, fn):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + '.pkl')
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    val = fn()
    pickle.dump(val, open(path, 'wb'))
    return val


# ── Ross premarket picks ──────────────────────────────────────────────────────

def ross_picks(conn):
    ledger = pd.read_sql("""SELECT symbol, upload_date, cells FROM ross_trade_ledger
                            WHERE status = 'matched'""", conn)
    bars = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et, open, high, low, close, volume
                          FROM ross_trade_bars_1m""", conn)
    bars['d'] = bars.et.dt.date
    bars['mins'] = bars.et.dt.hour * 60 + bars.et.dt.minute
    groups = {k: g.sort_values('et').reset_index(drop=True) for k, g in bars.groupby(['symbol', 'd'])}
    picks = []
    for r in ledger.itertuples():
        p = first_price(r.cells[3]) if len(r.cells) > 3 else None
        if p is None:
            continue
        for back in range(5):
            d = r.upload_date - timedelta(days=back)
            if d.weekday() < 5 and (r.symbol, d) in groups:
                g = groups[(r.symbol, d)]
                hit = np.where((g.low.values <= p) & (g.high.values >= p) & (g.mins.values >= PM_START)
                               & (g.volume.values >= 10_000))[0]
                if hit.size and g.mins.values[hit[0]] < OPEN:
                    picks.append({'symbol': r.symbol, 'day': d, 'touch': int(hit[0]),
                                  'pick_min': int(g.mins.values[hit[0]]), 'price': p})
                break
    df = pd.DataFrame(picks).drop_duplicates(['symbol', 'day'])
    return df, groups


# ── Stage 1: universe + prior-day close ───────────────────────────────────────

def universe_symbols(conn, ledger_syms):
    from dotenv import load_dotenv
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.trading.requests import GetAssetsRequest
    load_dotenv(r'C:/Repositories/Stock-Picker/production/.env.paper')
    tc = TradingClient(os.environ['APCA_PAPER_KEY_ID'], os.environ['APCA_PAPER_SECRET_KEY'], paper=True)
    syms = set()
    for st in (AssetStatus.ACTIVE, AssetStatus.INACTIVE):
        for a in tc.get_all_assets(GetAssetsRequest(asset_class=AssetClass.US_EQUITY, status=st)):
            if str(a.exchange).split('.')[-1] == 'ARCA' and st == AssetStatus.ACTIVE:
                continue  # active ARCA listings are ETFs
            syms.add(a.symbol)
    with conn.cursor() as cur:
        cur.execute('SELECT DISTINCT symbol FROM daily_gappers')
        syms |= {r[0] for r in cur.fetchall()}
        cur.execute("SELECT DISTINCT symbol FROM tradable_stocks_by_date")
        syms |= {r[0] for r in cur.fetchall()}
    syms |= set(ledger_syms)
    return sorted(s for s in syms if s and s.isalpha() and len(s) <= 5)


def prior_day_table(client, symbols, days):
    """{day: DataFrame[symbol, prior_close, prior_vol]} for each test day."""
    lo, hi = min(days) - timedelta(days=10), max(days)
    want = set()
    for d in days:
        for back in range(1, 8):
            want.add(d - timedelta(days=back))
    rows = []
    for i in range(0, len(symbols), BATCH):
        data = _fetch(client, symbols[i:i + BATCH], TimeFrame.Day,
                      ET.localize(datetime.combine(lo, datetime.min.time())),
                      ET.localize(datetime.combine(hi, datetime.min.time())))
        for sym, bars in data.items():
            for b in bars:
                dd = b.timestamp.astimezone(ET).date()
                if dd in want:
                    rows.append((sym, dd, b.close, b.volume))
        if (i // BATCH) % 20 == 0:
            log(f'  daily universe {i + BATCH}/{len(symbols)} symbols, {len(rows):,} rows kept')
    daily = pd.DataFrame(rows, columns=['symbol', 'd', 'close', 'volume']).sort_values(['symbol', 'd'])
    out = {}
    for d in days:
        prev = daily[daily.d < d].groupby('symbol').tail(1)
        prev = prev[prev.d >= d - timedelta(days=7)]
        out[d] = prev[['symbol', 'close', 'volume']].rename(columns={'close': 'prior_close', 'volume': 'prior_vol'})
    return out


# ── Stage 2: premarket scanner ────────────────────────────────────────────────

def scan_day(client, d, prior):
    elig = prior[(prior.prior_close.between(1, 20)) & (prior.prior_vol >= MIN_PRIOR_VOL)]
    pc = dict(zip(elig.symbol, elig.prior_close))
    syms = sorted(pc)
    start = ET.localize(datetime(d.year, d.month, d.day, 4, 0))
    end = ET.localize(datetime(d.year, d.month, d.day, 9, 30))
    hits = []
    for i in range(0, len(syms), BATCH):
        data = _fetch(client, syms[i:i + BATCH], TimeFrame(15, TimeFrameUnit.Minute), start, end)
        for sym, bars in data.items():
            cum = 0.0
            for b in sorted(bars, key=lambda x: x.timestamp):
                et = b.timestamp.astimezone(ET)
                cum += b.volume
                end_min = et.hour * 60 + et.minute + 15
                if end_min < PM_START or end_min > OPEN:
                    continue
                if cum >= MIN_PM_VOL and 1 <= b.close <= 20 and b.close >= pc[sym] * (1 + MIN_GAP):
                    hits.append({'symbol': sym, 'day': d, 'flag_min': end_min,
                                 'gap': b.close / pc[sym] - 1, 'pm_vol': cum})
                    break
    return hits, len(syms)


# ── scoring helpers ───────────────────────────────────────────────────────────

def minute_groups(conn, table):
    df = pd.read_sql(f"""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et, open, close
                         FROM {table}""", conn)
    df['d'] = df.et.dt.date
    df['mins'] = df.et.dt.hour * 60 + df.et.dt.minute
    return {k: g.sort_values('et').reset_index(drop=True) for k, g in df.groupby(['symbol', 'd'])}


def fwd(g, e):
    o, c = g.open.values, g.close.values
    out = {}
    for h in HOLDS:
        j = e + h - 1
        out[h] = (c[j] * (1 - SLIP) - o[e]) / o[e] if j < len(o) else np.nan
    return out


def window_mean(g, start_min, end_min, h):
    o, c, m = g.open.values, g.close.values, g.mins.values
    idx = np.where((m >= start_min) & (m < end_min))[0]
    r = [(c[i + h] * (1 - SLIP) - o[i + 1]) / o[i + 1] for i in idx if i + h < len(o)]
    return float(np.mean(r)) if r else np.nan


def ci(a, n=4000):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    if a.size < 5:
        return None
    b = RNG.choice(a, size=(n, a.size), replace=True).mean(axis=1)
    return a.size, a.mean(), np.median(a), (a > 0).mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def line(label, s):
    if s is None:
        return f'{label:<44} (n<5)'
    n, mean, med, pos, lo, hi = s
    return (f'{label:<44} n={n:>5}  mean {mean*100:+6.2f}%  median {med*100:+6.2f}%  '
            f'pos {pos:4.0%}  95% CI [{lo*100:+.2f}, {hi*100:+.2f}]')


def main():
    conn = psycopg2.connect(DSN)
    picks, ross_bars = ross_picks(conn)
    days = sorted(picks.day.unique())
    log(f'Ross premarket picks (07:00-09:29, est.): {len(picks)} stock-days over {len(days)} days')

    client = _client()
    symbols = cached('universe', lambda: universe_symbols(conn, picks.symbol.unique()))
    log(f'universe: {len(symbols):,} symbols')
    prior = cached('prior_day', lambda: prior_day_table(client, symbols, days))

    def scan_all():
        hits, sizes = [], []
        for i, d in enumerate(days, 1):
            h, n = scan_day(client, d, prior[d])
            hits += h
            sizes.append(n)
            if i % 25 == 0:
                log(f'  scanned {i}/{len(days)} days, {len(hits)} hits, ~{np.mean(sizes):.0f} eligible/day')
        return pd.DataFrame(hits)
    hits = cached('scanner_hits', scan_all)
    log(f'scanner hits: {len(hits)} ({len(hits) / len(days):.1f}/day)')

    with conn.cursor() as cur:
        cur.execute('CREATE TABLE IF NOT EXISTS ross_scanner_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL)')
        cur.execute("SELECT DISTINCT (time AT TIME ZONE 'America/New_York')::date FROM ross_scanner_bars_1m")
        have = {r[0] for r in cur.fetchall()}
    conn.commit()
    todo = [d for d in days if d not in have]
    log(f'fetching minute bars for scanner hits on {len(todo)} days')
    for i, d in enumerate(todo, 1):
        syms = sorted(hits[hits.day == d].symbol.unique())
        s = ET.localize(datetime(d.year, d.month, d.day, 4, 0))
        e = ET.localize(datetime(d.year, d.month, d.day, 12, 0))
        for j in range(0, len(syms), 50):
            _insert(conn, 'ross_scanner_bars_1m', _fetch(client, syms[j:j + 50], TimeFrame.Minute, s, e))
        conn.commit()
        if i % 100 == 0:
            log(f'  {i}/{len(todo)} days')
    scan_bars = minute_groups(conn, 'ross_scanner_bars_1m')
    conn.close()

    in_scan = set(zip(hits.symbol, hits.day))
    log(f'\nRoss premarket picks that our scanner also flagged that morning: '
        f'{sum((s, d) in in_scan for s, d in zip(picks.symbol, picks.day))}/{len(picks)}')
    both = picks.merge(hits, on=['symbol', 'day'])
    if len(both):
        early = (both.pick_min < both.flag_min).mean()
        log(f'  of those, Ross entered BEFORE the scanner flagged it: {early:.0%} '
            f'(median Ross {both.pick_min.median():.0f} vs flag {both.flag_min.median():.0f} min after midnight)')

    # A. scanner as a strategy
    log('\n=== A. Premarket scanner as a strategy: buy next minute after flag ===')
    a = {h: [] for h in HOLDS}
    for r in hits.itertuples():
        g = scan_bars.get((r.symbol, r.day))
        if g is None:
            continue
        idx = np.where(g.mins.values >= r.flag_min)[0]
        if idx.size:
            for h, v in fwd(g, int(idx[0])).items():
                a[h].append(v)
    for h in HOLDS:
        log(line(f'hold {h:>2} min', ci(a[h])))

    # B. Ross premarket entries one bar late
    log('\n=== B. Ross premarket entries, bot one minute late ===')
    b = {h: [] for h in HOLDS}
    for r in picks.itertuples():
        g = ross_bars[(r.symbol, r.day)]
        e = r.touch + 1
        if e < len(g):
            for h, v in fwd(g, e).items():
                b[h].append(v)
    for h in HOLDS:
        log(line(f'hold {h:>2} min', ci(b[h])))

    # C. selection, paired by day
    log('\n=== C. Selection: random entry from Ross pick time to 09:30, Ross stock vs scanner hits flagged by then ===')
    for h in (10, 30):
        diffs, ross_v, scan_v = [], [], []
        for d, grp in picks.groupby('day'):
            st = int(grp.pick_min.min())
            rv = [window_mean(ross_bars[(r.symbol, d)], st, OPEN, h) for r in grp.itertuples()]
            cands = hits[(hits.day == d) & (hits.flag_min <= st) & (~hits.symbol.isin(grp.symbol))]
            sv = [window_mean(scan_bars[(s, d)], st, OPEN, h) for s in cands.symbol if (s, d) in scan_bars]
            rv, sv = [x for x in rv if np.isfinite(x)], [x for x in sv if np.isfinite(x)]
            ross_v += rv
            scan_v += sv
            if rv and sv:
                diffs.append(np.mean(rv) - np.mean(sv))
        log(f'-- hold {h} min')
        log(line('Ross picks', ci(ross_v)))
        log(line('scanner hits already flagged', ci(scan_v)))
        log(line('PAIRED Ross minus scanner, same day', ci(diffs)))
    log('\nDONE')


if __name__ == '__main__':
    main()
