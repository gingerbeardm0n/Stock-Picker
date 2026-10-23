"""Level 2 (Nasdaq MBP-10 book) pilot on premarket small-cap movers.
PRE-REGISTERED in docs/PREREG_2026_10_L2_BOOK_PILOT.md (frozen before any data). One look; nothing here
may change after `evaluate` has been run on real data.

Subcommands (output dir research/analysis/outputs/l2_pilot/, gitignored):
  select                       sample per prereg -> selection.csv
  cost                         FREE metadata.get_cost per stock-morning, budget rule ($100 cap) -> costs.csv, budget.csv
  download --approved-usd X    the ONLY command that buys data; refuses without --approved-usd; aborts if the exact
                               get_cost total of files not yet on disk exceeds X or $100; saves .dbn.zst, never re-buys
  evaluate                     the one look (feature, 3 pass criteria, VERDICT, report-only items)
  selftest                     feature/outcome/stat code on synthetic MBP-10 data only

MONEY RULE: only metadata.get_cost / list_unit_prices / get_dataset_range / list_schemas and symbology.resolve are
free. timeseries.get_range is called in exactly one place (download), behind the approval gate.

Ambiguities resolved (closest to prereg text and earlier premarket tests):
  * flag_min = minutes after midnight ET of the flag minute (as in tape_feature_test.py). Data window =
    [flag minute start - 4 min, start of the minute after flag) ET. Entry time T0 = start of minute flag_min+1.
  * "newest first": sort by day desc, then flag_min asc, then symbol. Budget = longest PREFIX of that order whose
    cumulative get_cost is <= $100 (stop at the first row that would overflow; no skipping to cheaper rows).
    Unresolvable symbols (422 symbology_invalid_request) are excluded and cost nothing.
  * Seconds: sample times t_k = T0 - 120s + k s, k=1..120; book state = last MBP-10 record with ts_event < t_k
    (strictly before, so nothing at/after entry leaks in). Seconds with no state yet, or empty on both sides, are
    skipped; one-sided books count (imbalance +-1). >= 60 valid seconds required. Imbalance exactly 0 is neither
    bid-heavy nor ask-heavy.
  * Entry = open of the first SIP bar with minute >= flag_min+1 (premarket bars are sparse; same convention as the
    earlier premarket tests, which took the first bar >= flag minute). Exit = close of the last bar whose minute is
    within entry_minute .. entry_minute+9. Cost 0.5% per side applied multiplicatively as in tape_feature_test.
  * Pass (b): CI of (bid-heavy mean - ask-heavy mean) uses gross 10-min returns, day-clustered bootstrap (costs
    cancel). Pass (c): bid-heavy mean NET return per trade > 0 (point estimate; CI shown but not required).
  * Thin ask = ask size summed over levels 1-10 at the last valid sample second / SIP volume of the flag-minute bar.
  * Nasdaq share = sum of mbp-10 trade-action sizes in the 5-minute data window / SIP volume of bars in
    [flag-4, flag] minutes.
  * Nasdaq listing = Alpaca /assets exchange == NASDAQ (active+inactive; symbol reuse not disambiguated).
"""
import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ET = pytz.timezone('America/New_York')
OUT = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'l2_pilot'))
HITS = os.path.abspath(os.path.join(HERE, '..', 'outputs', 'premarket_float_hits.csv'))
DATASET, SCHEMA = 'XNAS.ITCH', 'mbp-10'
MIN_DAY = pd.Timestamp('2018-05-01').date()
BUDGET_CAP, MIN_FIT = 100.0, 200
PRE_MIN, FEAT_SECS, MIN_VALID = 4, 120, 60
COST_SIDE = 0.005
BOOT = 3000
RNG = np.random.default_rng(20261023)
ENVFILE = r'C:/Repositories/Stock-Picker/production/.env.paper'


def log(*a):
    print(*a, flush=True)


# ── helpers ───────────────────────────────────────────────────────────────────

def window(day, flag_min):
    """(start, end) tz-aware ET: flag minute start - 4 min .. start of minute after flag."""
    base = ET.localize(datetime(day.year, day.month, day.day))
    return base + pd.Timedelta(minutes=int(flag_min) - PRE_MIN), base + pd.Timedelta(minutes=int(flag_min) + 1)


def fpath(day, sym):
    return os.path.join(OUT, 'mbp10', f'{day}_{sym}.dbn.zst')


def hist_client():
    import databento as db
    load_dotenv(ENVFILE)
    return db.Historical(os.environ['DATABENTO_API_KEY'])  # key never printed


def load_selection():
    return pd.read_csv(os.path.join(OUT, 'selection.csv'), dtype={'symbol': str}, keep_default_na=False,
                       parse_dates=['day']).assign(day=lambda d: d.day.dt.date)


# ── select ────────────────────────────────────────────────────────────────────

def nasdaq_symbols():
    path = os.path.join(OUT, 'asset_exchange.json')
    if os.path.exists(path):
        m = json.load(open(path))
    else:
        from alpaca.trading.client import TradingClient
        load_dotenv(ENVFILE)
        tc = TradingClient(os.environ['APCA_PAPER_KEY_ID'], os.environ['APCA_PAPER_SECRET_KEY'], paper=True)
        m = {}
        for st in ('active', 'inactive'):
            # read-only GET of assets; raw REST because alpaca-py rejects exchanges it does not know (TXSE)
            for a in tc.get('/assets', {'status': st, 'asset_class': 'us_equity'}):
                s = a.get('symbol') or ''
                if s and (s not in m or st == 'active'):
                    m[s] = a.get('exchange') or ''
        os.makedirs(OUT, exist_ok=True)
        json.dump(m, open(path, 'w'))
    return {s for s, e in m.items() if e == 'NASDAQ'}


def cmd_select(_):
    df = pd.read_csv(HITS, usecols=['symbol', 'day', 'flag_min', 'label'], dtype={'symbol': str},
                     keep_default_na=False, parse_dates=['day'])
    df['day'] = df.day.dt.date
    df['flag_min'] = pd.to_numeric(df.flag_min)
    n0 = len(df)
    df = df[(df.flag_min < 570) & (df.day >= MIN_DAY)]
    n1 = len(df)
    nas = nasdaq_symbols()
    df = df[df.symbol.isin(nas)].drop_duplicates(['symbol', 'day'])
    df = df.sort_values(['day', 'flag_min', 'symbol'], ascending=[False, True, True]).reset_index(drop=True)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, 'selection.csv'), index=False)
    log(f'hits {n0}; premarket & >= {MIN_DAY}: {n1}; Nasdaq-listed: {len(df)} (dropped non-Nasdaq: {n1 - len(df)})')
    if len(df):
        log(f'day range {df.day.min()} .. {df.day.max()}')


# ── cost (free) ───────────────────────────────────────────────────────────────

def cmd_cost(_):
    sel = load_selection()
    client = hist_client()
    cpath = os.path.join(OUT, 'costs.csv')
    done = {}
    if os.path.exists(cpath):
        c = pd.read_csv(cpath, dtype={'symbol': str}, keep_default_na=False)
        done = {(r.symbol, r.day): (r.cost, r.status) for r in c.itertuples()}
    from concurrent.futures import ThreadPoolExecutor

    def price(r):
        s, e = window(r.day, r.flag_min)
        for attempt in range(4):
            try:
                return float(client.metadata.get_cost(dataset=DATASET, symbols=r.symbol, schema=SCHEMA,
                                                      start=s, end=e, stype_in='raw_symbol')), 'ok'
            except Exception as ex:  # noqa: BLE001
                msg = str(ex)
                if '422' in msg or 'symbology_invalid' in msg or 'invalid' in msg.lower():
                    return 0.0, 'unresolvable'
                time.sleep(2 * (attempt + 1))
        return None, 'error'

    todo = [r for r in sel.itertuples() if (r.symbol, str(r.day)) not in done]
    log(f'{len(done)} already priced, {len(todo)} to price (free get_cost, 8 threads)')
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex:
        for i, (r, res) in enumerate(zip(todo, ex.map(price, todo)), 1):
            if res[1] != 'error':
                done[(r.symbol, str(r.day))] = res
            if i % 200 == 0:
                log(f'  {i}/{len(todo)} priced, {time.time() - t0:.0f}s')
    rows, cum, nfit, stopped = [], 0.0, 0, False
    for r in sel.itertuples():
        key = (r.symbol, str(r.day))
        if key not in done:
            log('WARNING: unpriced (errors) row', key)
            continue
        cost, status = done[key]
        rows.append((r.symbol, str(r.day), r.flag_min, cost, status))
        if status == 'ok':
            if cum + cost > BUDGET_CAP:
                stopped = True
                break
            cum += cost
            nfit += 1
    cdf = pd.DataFrame(rows, columns=['symbol', 'day', 'flag_min', 'cost', 'status'])
    cdf.to_csv(cpath, index=False)
    ok = cdf[cdf.status == 'ok'].iloc[:nfit]
    ok.to_csv(os.path.join(OUT, 'budget.csv'), index=False)
    log(f'priced rows {len(cdf)}; unresolvable {int((cdf.status == "unresolvable").sum())}; '
        f'budget cap reached: {stopped}')
    log(f'BUDGET SELECTION: n={len(ok)}  total ${ok.cost.sum():.4f}  mean ${ok.cost.mean():.4f}  '
        f'max ${ok.cost.max():.4f}')
    if len(ok) < MIN_FIT:
        log(f'*** fewer than {MIN_FIT} fit in ${BUDGET_CAP:.0f}: prereg says STOP, do not buy, report to Joel')


# ── download (the only paid step) ─────────────────────────────────────────────

def cmd_download(a):
    if a.approved_usd is None:
        sys.exit('refusing: --approved-usd X is required')
    bp = os.path.join(OUT, 'budget.csv')
    if not os.path.exists(bp):
        sys.exit('run `cost` first')
    bud = pd.read_csv(bp, dtype={'symbol': str}, keep_default_na=False)
    if len(bud) < MIN_FIT:
        sys.exit(f'refusing: only {len(bud)} stock-mornings fit the budget (< {MIN_FIT}); prereg says do not buy')
    client = hist_client()
    os.makedirs(os.path.join(OUT, 'mbp10'), exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    todo = []
    for r in bud.itertuples():
        day = pd.Timestamp(r.day).date()
        if not os.path.exists(fpath(day, r.symbol)):
            todo.append((day, r.symbol) + window(day, r.flag_min))

    def _price(t):
        day, sym, s, e = t
        return float(client.metadata.get_cost(dataset=DATASET, symbols=sym, schema=SCHEMA, start=s, end=e,
                                              stype_in='raw_symbol'))

    log(f'pricing {len(todo)} files still to buy (free get_cost, 8 threads)')
    with ThreadPoolExecutor(8) as ex:
        costs = list(ex.map(_price, todo))
    pend, total = todo, float(sum(costs))
    full = float(bud.cost.sum())
    log(f'EXACT get_cost total for {len(pend)} files still to buy: ${total:.4f} (full selection ${full:.4f})')
    if total > a.approved_usd:
        sys.exit(f'ABORT: total ${total:.4f} > approved ${a.approved_usd}')
    if total > BUDGET_CAP or full > BUDGET_CAP:
        sys.exit(f'ABORT: exceeds prereg cap ${BUDGET_CAP}')

    def _get(t):
        day, sym, s, e = t
        p = fpath(day, sym)
        client.timeseries.get_range(dataset=DATASET, symbols=sym, schema=SCHEMA, start=s, end=e,
                                    stype_in='raw_symbol', path=p + '.part')
        os.replace(p + '.part', p)

    with ThreadPoolExecutor(8) as ex:
        for i, _ in enumerate(ex.map(_get, pend), 1):
            if i % 200 == 0 or i == len(pend):
                log(f'  saved {i}/{len(pend)}')
    log('download done')


# ── feature (pure functions; tested on synthetic data) ────────────────────────

def _depth_arrays(df):
    b = df[[f'bid_sz_{i:02d}' for i in range(10)]].fillna(0).to_numpy(float).sum(1)
    a = df[[f'ask_sz_{i:02d}' for i in range(10)]].fillna(0).to_numpy(float).sum(1)
    return b, a


def book_features(df, t0):
    """df: mbp-10 DataFrame (ts_event index, UTC). t0: tz-aware entry time.
    Returns dict(imb, imb30, n_valid, ask_depth, nas_vol) or None if < MIN_VALID valid seconds."""
    df = df.sort_index()
    if 'instrument_id' in df.columns and df.instrument_id.nunique() > 1:
        df = df[df.instrument_id == df.instrument_id.value_counts().idxmax()]
    ts = df.index.tz_convert('UTC').asi8
    b, a = _depth_arrays(df)
    t0n = pd.Timestamp(t0).tz_convert('UTC').value
    ticks = t0n - FEAT_SECS * 10**9 + np.arange(1, FEAT_SECS + 1) * 10**9
    pos = np.searchsorted(ts, ticks, side='left') - 1  # last record strictly before the sample time
    has = pos >= 0
    bb = np.where(has, b[np.clip(pos, 0, None)], 0.0)
    aa = np.where(has, a[np.clip(pos, 0, None)], 0.0)
    ok = has & ((bb + aa) > 0)
    nvalid = int(ok.sum())
    nas_vol = float(df.loc[(df.action == 'T'), 'size'].sum()) if 'action' in df.columns else np.nan
    if nvalid < MIN_VALID:
        return None
    imb = (bb - aa)[ok] / (bb + aa)[ok]
    k = ok.copy()
    k[:FEAT_SECS - 30] = False
    imb30 = ((bb - aa)[k] / (bb + aa)[k]).mean() if k.any() else np.nan
    last = np.where(ok)[0][-1]
    return dict(imb=float(imb.mean()), imb30=float(imb30), n_valid=nvalid, ask_depth=float(aa[last]),
                nas_vol=nas_vol)


def net_ret(e, x, c=COST_SIDE):
    return x * (1 - c) / (e * (1 + c)) - 1


def trade_outcome(bars, flag_min):
    """bars=(m,o,h,l,c,v) arrays for symbol-day. Returns dict(ep, x10, x30, vol_flag, vol_win, delay) or None."""
    m, o, h, l, c, v = bars
    k = np.where(m >= flag_min + 1)[0]
    if not k.size:
        return None
    e = int(k[0])
    row = {'ep': float(o[e]), 'delay': int(m[e] - (flag_min + 1))}
    for hh in (10, 30):
        ks = np.where((m >= m[e]) & (m <= m[e] + hh - 1))[0]
        row[f'x{hh}'] = float(c[ks[-1]])
    fm = np.where(m == flag_min)[0]
    row['vol_flag'] = float(v[fm[0]]) if fm.size else np.nan
    row['vol_win'] = float(v[(m >= flag_min - PRE_MIN) & (m <= flag_min)].sum())
    return row


def dci(values, days):
    s = pd.DataFrame({'v': values, 'd': days}).dropna()
    if len(s) < 10:
        return None
    g = s.groupby('d').v.agg(['sum', 'count'])
    su, n = g['sum'].values, g['count'].values
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    bt = su[idx].sum(1) / n[idx].sum(1)
    return len(s), s.v.mean(), np.percentile(bt, 2.5), np.percentile(bt, 97.5), len(g)


def diff_ci(v, days, hi_mask, lo_mask):
    """Day-clustered bootstrap CI of mean(v | hi) - mean(v | lo)."""
    s = pd.DataFrame({'v': v, 'd': days, 'h': hi_mask, 'l': lo_mask})
    g = s.groupby('d').apply(lambda x: pd.Series({
        'hs': x.v[x.h].sum(), 'hn': x.h.sum(), 'ls': x.v[x.l].sum(), 'ln': x.l.sum()}), include_groups=False)
    if g.hn.sum() < 5 or g.ln.sum() < 5:
        return None
    idx = RNG.integers(0, len(g), size=(BOOT, len(g)))
    hn, ln = g.hn.values[idx].sum(1), g.ln.values[idx].sum(1)
    with np.errstate(invalid='ignore', divide='ignore'):
        bt = g.hs.values[idx].sum(1) / hn - g.ls.values[idx].sum(1) / ln
    bt = bt[np.isfinite(bt)]
    pt = g.hs.sum() / g.hn.sum() - g.ls.sum() / g.ln.sum()
    return pt, np.percentile(bt, 2.5), np.percentile(bt, 97.5), int(g.hn.sum()), int(g.ln.sum())


# ── evaluate ──────────────────────────────────────────────────────────────────

def analyze(d, out):
    """d: DataFrame with symbol, day, label, imb, imb30, ask_depth, vol_flag, nas_vol, vol_win, ep, x10, x30.
    Prints via out(); returns verdict string."""
    d = d.copy()
    d['year'] = pd.to_datetime(d.day).dt.year
    for hh in (10, 30):
        d[f'g{hh}'] = d[f'x{hh}'] / d.ep - 1
        d[f'n{hh}'] = net_ret(d.ep.values, d[f'x{hh}'].values)
    bid, ask = d.imb > 0, d.imb < 0
    out(f'valid stock-mornings (feature + outcome): {len(d)}; days {d.day.nunique()}; '
        f'bid-heavy {int(bid.sum())}, ask-heavy {int(ask.sum())}, exactly 0: {int((d.imb == 0).sum())}')
    a_ok = len(d) >= 200
    df10 = diff_ci(d.g10.values, d.day.values, bid.values, ask.values)
    b_ok = df10 is not None and df10[1] > 0
    bn = dci(d.n10[bid].values, d.day[bid].values)
    c_ok = bn is not None and bn[1] > 0
    out('--- DECISION CRITERIA ---')
    out(f'(a) n >= 200: {len(d)} -> {"PASS" if a_ok else "FAIL"}')
    if df10:
        out(f'(b) bid-heavy minus ask-heavy gross 10m mean {df10[0]*100:+.3f}%  CI [{df10[1]*100:+.3f}, '
            f'{df10[2]*100:+.3f}]  (n bid {df10[3]}, ask {df10[4]}) -> {"PASS" if b_ok else "FAIL"}')
    else:
        out('(b) too few bid-heavy/ask-heavy -> FAIL')
    if bn:
        out(f'(c) bid-heavy net 10m mean/trade @0.5%/side {bn[1]*100:+.3f}%  CI [{bn[2]*100:+.3f}, '
            f'{bn[3]*100:+.3f}]  n={bn[0]} -> {"PASS" if c_ok else "FAIL"}')
    else:
        out('(c) too few bid-heavy -> FAIL')
    verdict = 'PASS' if (a_ok and b_ok and c_ok) else 'FAIL'
    out(f'VERDICT: {verdict}  (a={a_ok} b={b_ok} c={c_ok})')

    out('--- REPORT ONLY (not used to decide) ---')
    try:
        d['terc'] = pd.qcut(d.imb, 3, labels=['low', 'mid', 'high'], duplicates='drop')
        for t, g in d.groupby('terc', observed=True):
            out(f'imbalance tercile {t}: n={len(g)} gross10 {g.g10.mean()*100:+.3f}% net10 {g.n10.mean()*100:+.3f}% '
                f'imb mean {g.imb.mean():+.3f}')
    except ValueError as ex:
        out(f'terciles unavailable: {ex}')
    b30, a30 = d.imb30 > 0, d.imb30 < 0
    r = diff_ci(d.g10.values, d.day.values, b30.values, a30.values)
    out('imb30 bid-minus-ask gross10: ' + (f'{r[0]*100:+.3f}% CI [{r[1]*100:+.3f}, {r[2]*100:+.3f}]' if r else 'n/a'))
    thin = d.ask_depth / d.vol_flag.replace(0, np.nan)
    d['thin'] = thin
    ok = thin.notna() & np.isfinite(thin)
    if ok.sum() > 10:
        out(f'thin ask (ask depth / flag-minute vol): median {thin[ok].median():.3f}; corr with gross10 '
            f'{np.corrcoef(thin[ok].rank(), d.g10[ok].rank())[0, 1]:+.3f} (rank, n={int(ok.sum())})')
        lo = thin <= thin[ok].median()
        r = diff_ci(d.g10.values, d.day.values, (ok & lo).values, (ok & ~lo).values)
        out('  thin-ask (<= median) minus thick-ask gross10: ' +
            (f'{r[0]*100:+.3f}% CI [{r[1]*100:+.3f}, {r[2]*100:+.3f}]' if r else 'n/a'))
    sh = (d.nas_vol / d.vol_win.replace(0, np.nan)).replace([np.inf], np.nan).dropna()
    out(f'Nasdaq share of SIP volume (5-min window): n={len(sh)} median {sh.median():.3f} mean {sh.mean():.3f}'
        if len(sh) else 'Nasdaq share: n/a')
    for lab, g in d.groupby('label'):
        gb, ga = g[g.imb > 0], g[g.imb < 0]
        out(f'label={lab} ({"Ross pick" if lab == 1 else "other hit"}): n={len(g)} bid-heavy n={len(gb)} '
            f'gross10 {gb.g10.mean()*100:+.3f}%  ask-heavy n={len(ga)} gross10 {ga.g10.mean()*100:+.3f}%')
    r30 = diff_ci(d.g30.values, d.day.values, bid.values, ask.values)
    out('30m hold bid-minus-ask gross: ' + (f'{r30[0]*100:+.3f}% CI [{r30[1]*100:+.3f}, {r30[2]*100:+.3f}]' if r30 else 'n/a'))
    for y, g in d.groupby('year'):
        gb, ga = g[g.imb > 0], g[g.imb < 0]
        out(f'year {y}: n={len(g)} bid-heavy gross10 {gb.g10.mean()*100:+.3f}% (n={len(gb)}) ask-heavy '
            f'{ga.g10.mean()*100:+.3f}% (n={len(ga)})')
    return verdict


def cmd_evaluate(_):
    import databento as db
    import psycopg2
    from ross_premarket_test import DSN
    from premarket_pullback_test import load_bars
    bud = pd.read_csv(os.path.join(OUT, 'budget.csv'), dtype={'symbol': str}, keep_default_na=False)
    sel = load_selection().set_index(['symbol', 'day'])
    conn = psycopg2.connect(DSN)
    bars = load_bars(conn)
    conn.close()
    rows, dropped = [], {'no_file': 0, 'feature': 0, 'no_outcome': 0}
    for r in bud.itertuples():
        day = pd.Timestamp(r.day).date()
        p = fpath(day, r.symbol)
        if not os.path.exists(p):
            dropped['no_file'] += 1
            continue
        s, e = window(day, r.flag_min)
        f = book_features(db.DBNStore.from_file(p).to_df(), e)
        if f is None:
            dropped['feature'] += 1
            continue
        a = bars.get((r.symbol, day))
        o = trade_outcome(a, r.flag_min) if a is not None else None
        if o is None:
            dropped['no_outcome'] += 1
            continue
        rows.append({'symbol': r.symbol, 'day': day, 'label': sel.loc[(r.symbol, day), 'label'], **f, **o})
    d = pd.DataFrame(rows)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(OUT, f'evaluate_{ts}.txt')
    fh = open(path, 'w')

    def out(s):
        log(s)
        fh.write(s + '\n')
    out(f'dropped: {dropped}')
    if d.empty:
        out('VERDICT: FAIL  (no valid stock-mornings)')
        return
    analyze(d, out)
    tp = os.path.join(os.path.dirname(OUT), 'tape_features.csv')
    if os.path.exists(tp):
        t = pd.read_csv(tp, dtype={'symbol': str}, keep_default_na=False, parse_dates=['day'])
        t['day'] = t.day.dt.date
        m = d.merge(t, on=['symbol', 'day'])
        for c in [c for c in m.columns if c.startswith('f_')]:
            out(f'corr(imb, {c}) = {m.imb.corr(m[c]):+.3f} (n={m[[c]].notna().sum().iloc[0]})')
    fh.close()
    log('saved', path)


# ── selftest (synthetic only) ─────────────────────────────────────────────────

def synth_book(t0, bid_sz, ask_sz, n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.DatetimeIndex(sorted(t0.tz_convert('UTC') - pd.to_timedelta(rng.uniform(1, 230, n), unit='s')),
                           name='ts_event')
    df = pd.DataFrame(index=idx)
    for i in range(10):
        df[f'bid_px_{i:02d}'] = 5.0 - 0.01 * i
        df[f'ask_px_{i:02d}'] = 5.01 + 0.01 * i
        df[f'bid_sz_{i:02d}'] = bid_sz
        df[f'ask_sz_{i:02d}'] = ask_sz
    df['action'] = 'A'
    df.iloc[::10, df.columns.get_loc('action')] = 'T'
    df['side'] = 'B'
    df['size'] = 100
    df['price'] = 5.0
    return df


def cmd_selftest(_):
    t0 = pd.Timestamp(ET.localize(datetime(2024, 3, 5, 8, 11)))
    f = book_features(synth_book(t0, 300, 100), t0)
    assert f and abs(f['imb'] - 0.5) < 1e-9 and abs(f['imb30'] - 0.5) < 1e-9, f  # (3000-1000)/4000
    f = book_features(synth_book(t0, 100, 300), t0)
    assert abs(f['imb'] + 0.5) < 1e-9
    # empty ask side: imbalance +1, still valid; both empty: skipped -> dropped
    assert abs(book_features(synth_book(t0, 100, 0), t0)['imb'] - 1) < 1e-9
    assert book_features(synth_book(t0, 0, 0), t0) is None
    # records at/after entry must not leak: add a huge-ask record at t0
    b = synth_book(t0, 300, 100)
    leak = b.iloc[[-1]].copy()
    leak.index = pd.DatetimeIndex([t0.tz_convert('UTC')], name='ts_event')
    for i in range(10):
        leak[f'ask_sz_{i:02d}'] = 1e6
    assert abs(book_features(pd.concat([b, leak]), t0)['imb'] - 0.5) < 1e-9
    # too few seconds with state -> None (book first appears 30s before entry)
    short = synth_book(t0, 300, 100)
    short.index = pd.DatetimeIndex(short.index.to_series().clip(lower=t0.tz_convert('UTC') - pd.Timedelta(seconds=30)))
    short.index.name = 'ts_event'
    assert book_features(short, t0) is None
    # outcome + stats on synthetic data with a planted bid-heavy edge
    m = np.arange(480, 520)
    bars = (m, np.full(40, 5.0), np.full(40, 5.1), np.full(40, 4.9), np.full(40, 5.2), np.full(40, 1000.0))
    o = trade_outcome(bars, 500)
    assert o['ep'] == 5.0 and o['x10'] == 5.2 and o['delay'] == 0 and o['vol_flag'] == 1000.0, o
    rng = np.random.default_rng(1)
    n = 600
    imb = rng.uniform(-1, 1, n)
    ret = 0.04 * imb + rng.normal(0, 0.02, n)
    d = pd.DataFrame({'symbol': 'X', 'day': pd.to_datetime('2024-01-01') + pd.to_timedelta(rng.integers(0, 150, n), 'D'),
                      'label': rng.integers(0, 2, n), 'imb': imb, 'imb30': imb, 'ask_depth': rng.uniform(500, 2000, n),
                      'vol_flag': 5000.0, 'nas_vol': 800.0, 'vol_win': 8000.0, 'ep': 5.0, 'x10': 5.0 * (1 + ret),
                      'x30': 5.0 * (1 + ret)})
    d['day'] = d.day.dt.date
    lines = []
    v = analyze(d, lines.append)
    assert v == 'PASS', lines
    d['x10'] = 5.0 * (1 - 0.01 * imb + rng.normal(0, 0.02, n))
    v2 = analyze(d, lambda s: None)
    assert v2 == 'FAIL'
    log('\n'.join(lines[:8]))
    log('SELFTEST OK (synthetic data only)')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    for n in ('select', 'cost', 'evaluate', 'selftest'):
        sp.add_parser(n)
    dl = sp.add_parser('download')
    dl.add_argument('--approved-usd', type=float, default=None)
    a = ap.parse_args()
    globals()['cmd_' + a.cmd](a)


if __name__ == '__main__':
    main()
