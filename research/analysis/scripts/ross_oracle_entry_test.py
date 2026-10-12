"""Oracle test (rough pass): do Ross Cameron's OWN entries make money for a bot one bar late?

If a bot that knew exactly what Ross bought, and roughly when, still loses after entering one
1-minute bar later with honest fills, then no model trained on 1-minute bars can copy his
edge (it lives in speed, tape/L2, or his exits). If it makes money, there is a reachable
target in our data.

Inputs (built by research/data_backfill/backfill_ross_ledger.py):
  ross_trade_ledger   trades parsed from the corpus summaries, with inferred trade_date
  ross_trade_bars_1m  Alpaca SIP 1-min bars, 04:00-12:00 ET, for those symbol-days

ROUGH: entry TIME is not in most summaries, so it is estimated as the first minute whose
[low, high] contains Ross's stated entry price (first number in the PRICE column).
Two estimates are reported:
  T1  first touch at any time 04:00-12:00
  T2  first touch at/after 07:00 on a bar with >= 10k shares (when Ross is actually trading)
Validation of the timing method: Ross's own WIN trades should look better than his LOSS
trades from the estimated entry. If they don't, the timing estimate is noise.

Control: a random bar between 07:00 and 11:00 on the same stock-day, same rules. Ross's
timing only matters if it beats random timing on the same stocks.

Bot entry = open of the bar after the touch bar (one bar late). Two exit families:
  fixed hold N bars  -> close of entry_idx + N, less 0.3% slippage
  structural         -> stop = touch-bar low - $0.01, target = 2R, time exit at 30 bars;
                        honest fills (stop: gap -> open, else min(stop, next open);
                        target/time: next open), 0.3% exit slippage. Reported in R.

Usage:  python research/analysis/scripts/ross_oracle_entry_test.py
Per-trade rows -> research/analysis/outputs/ross_oracle_trades.csv (gitignored)
"""
import os
import re
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg2

DSN = os.environ.get('STOCKDATA_DSN', 'postgresql://postgres:changeme123@localhost:5432/stockdata')
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs'))
HOLDS = [1, 3, 5, 10, 15, 30]
SLIP = 0.003
TIME_EXIT = 30
RNG = np.random.default_rng(20261008)
BOOT = 2000


def first_price(s):
    m = re.search(r'\$?\s*(\d+(?:\.\d+)?)', s or '')
    return float(m.group(1)) if m else None


def setup_bucket(text):
    t = (text or '').lower()
    for key, words in [('micro-pullback', ['micro pull', 'micro-pull']),
                       ('halt-resume', ['halt']),
                       ('vwap', ['vwap']),
                       ('gap-and-go', ['gap-and-go', 'gap and go']),
                       ('dip/pullback', ['dip', 'pullback', 'pull back']),
                       ('breakout', ['breakout', 'break of', 'flat top', 'flat-top', 'whole dollar', 'high of day']),
                       ]:
        if any(w in t for w in words):
            return key
    return 'other'


def load():
    conn = psycopg2.connect(DSN)
    ledger = pd.read_sql("""SELECT file_num, trade_idx, symbol, trade_date, cells
                            FROM ross_trade_ledger WHERE status = 'matched'""", conn)
    bars = pd.read_sql("""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et,
                                 open, high, low, close, volume
                          FROM ross_trade_bars_1m ORDER BY symbol, time""", conn)
    conn.close()
    bars['d'] = bars['et'].dt.date
    bars['mins'] = bars['et'].dt.hour * 60 + bars['et'].dt.minute
    groups = {k: g.reset_index(drop=True) for k, g in bars.groupby(['symbol', 'd'])}
    return ledger, groups


def structural_exit(b, touch, e):
    """Honest structural exit. Returns (R multiple, pct return) or None."""
    entry = b.open[e]
    stop = b.low[touch] - 0.01
    if stop >= entry * 0.995:          # gapped above the stop zone: use a 2% stop
        stop = entry * 0.98
    risk = entry - stop
    target = entry + 2 * risk
    n = len(b.open)
    fill = None
    for j in range(e, min(n, e + TIME_EXIT)):
        if j > e and b.open[j] <= stop:
            fill = b.open[j]
            break
        if b.low[j] <= stop:
            fill = min(stop, b.open[j + 1]) if j + 1 < n else b.close[j]
            break
        if b.high[j] >= target:
            fill = b.open[j + 1] if j + 1 < n else b.close[j]
            break
    if fill is None:
        j = min(n - 1, e + TIME_EXIT)
        fill = b.open[j]
    fill *= (1 - SLIP)
    return (fill - entry) / risk, (fill - entry) / entry


def evaluate(b, touch):
    """Forward returns for a bot entering at the open of touch+1."""
    e = touch + 1
    n = len(b.open)
    if e >= n:
        return None
    entry = b.open[e]
    row = {}
    for h in HOLDS:
        j = e + h - 1
        if j < n:
            row[f'h{h}'] = (b.close[j] * (1 - SLIP) - entry) / entry
    win = slice(e, min(n, e + 15))
    row['mfe15'] = (b.high[win].max() - entry) / entry
    row['mae15'] = (b.low[win].min() - entry) / entry
    row['R'], row['struct'] = structural_exit(b, touch, e)
    return row


class B:
    """Bars as plain numpy arrays (fast indexing)."""
    def __init__(self, g):
        self.open, self.high, self.low = g.open.values, g.high.values, g.low.values
        self.close, self.volume, self.mins = g.close.values, g.volume.values, g.mins.values


def stats(xs):
    a = np.asarray([x for x in xs if x is not None and np.isfinite(x)], dtype=float)
    if a.size < 5:
        return None
    boots = RNG.choice(a, size=(BOOT, a.size), replace=True).mean(axis=1)
    return a.size, a.mean(), np.median(a), (a > 0).mean(), np.percentile(boots, 2.5), np.percentile(boots, 97.5)


def fmt(label, s, pct=True):
    if s is None:
        return f'{label:<34} (n<5)'
    n, mean, med, pos, lo, hi = s
    k = 100 if pct else 1
    u = '%' if pct else 'R'
    return (f'{label:<34} n={n:>5}  mean {mean*k:+6.2f}{u}  median {med*k:+6.2f}{u}  '
            f'pos {pos:4.0%}  95% CI [{lo*k:+.2f}, {hi*k:+.2f}]')


def main():
    ledger, groups = load()
    rows, skipped = [], defaultdict(int)
    for r in ledger.itertuples():
        cells = r.cells
        if len(cells) < 10:
            skipped['short_row'] += 1
            continue
        p = first_price(cells[3])
        g = groups.get((r.symbol, r.trade_date))
        if p is None or g is None or len(g) < 5:
            skipped['no_price_or_bars'] += 1
            continue
        b = B(g)
        hit = (b.low <= p) & (b.high >= p)
        if not hit.any():
            skipped['price_never_traded'] += 1
            continue
        t1 = int(np.argmax(hit))
        cand2 = np.where(hit & (b.mins >= 420) & (b.volume >= 10_000))[0]
        t2 = int(cand2[0]) if cand2.size else None
        ctrl_pool = np.where((b.mins >= 420) & (b.mins < 660))[0]
        tc = int(RNG.choice(ctrl_pool)) if ctrl_pool.size else None
        base = {'file': r.file_num, 'idx': r.trade_idx, 'symbol': r.symbol, 'date': r.trade_date,
                'price': p, 'range_price': '-' in cells[3], 'setup': setup_bucket(cells[6]),
                'outcome': cells[9].strip().upper(), 'year': r.trade_date.year}
        for tag, touch in (('T1', t1), ('T2', t2), ('CTRL', tc)):
            if touch is None:
                continue
            ev = evaluate(b, touch)
            if ev:
                rows.append({**base, 'basis': tag, 'touch_min': int(b.mins[touch]), **ev})
    df = pd.DataFrame(rows)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, 'ross_oracle_trades.csv'), index=False)

    print(f'ledger matched trades: {len(ledger)} | skipped: {dict(skipped)}')
    for tag in ('T1', 'T2', 'CTRL'):
        d = df[df.basis == tag]
        print(f'\n=== {tag} ({"first touch" if tag == "T1" else "first touch >=7:00, >=10k vol" if tag == "T2" else "random bar 7:00-11:00, same stock-days"}) ===')
        if tag != 'CTRL':
            tm = d.touch_min
            print(f'estimated entry time: <7:00 {np.mean(tm < 420):.0%} | 7:00-9:30 {np.mean((tm >= 420) & (tm < 570)):.0%}'
                  f' | 9:30+ {np.mean(tm >= 570):.0%}')
        for h in HOLDS:
            print(fmt(f'hold {h:>2} bars', stats(d[f'h{h}'])))
        print(fmt('structural (stop/2R/30bar), %', stats(d['struct'])))
        print(fmt('structural, R', stats(d['R']), pct=False))
        print(f'MFE15 mean {d.mfe15.mean()*100:+.2f}%  MAE15 mean {d.mae15.mean()*100:+.2f}%')

    for tag in ('T1', 'T2'):
        d = df[df.basis == tag]
        print(f'\n--- {tag}: timing validation — by Ross outcome (hold 5 / structural R) ---')
        for oc in ('WIN', 'LOSS'):
            x = d[d.outcome == oc]
            print(fmt(f'{oc} hold5', stats(x.h5)))
            print(fmt(f'{oc} structural R', stats(x.R), pct=False))
        print(f'--- {tag}: by setup (structural R) ---')
        for s, x in d.groupby('setup'):
            print(fmt(f'{s}', stats(x.R), pct=False))
        print(f'--- {tag}: by entry window (structural R) ---')
        for lab, m in (('premarket <9:30', d.touch_min < 570), ('after open 9:30+', d.touch_min >= 570)):
            print(fmt(lab, stats(d[m].R), pct=False))
        print(f'--- {tag}: single-price rows only (cleaner) ---')
        x = d[~d.range_price]
        print(fmt('hold5', stats(x.h5)))
        print(fmt('structural R', stats(x.R), pct=False))
        print(f'--- {tag}: by year (structural R) ---')
        for y, x in d.groupby('year'):
            print(fmt(str(y), stats(x.R), pct=False))
    print('\nDONE')


if __name__ == '__main__':
    main()
