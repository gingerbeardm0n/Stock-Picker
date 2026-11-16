"""Check Lightspeed order-log fills (ross_lightspeed_log_reader.py output) against Alpaca SIP ticks.

For each video CSV, filled rows only. Trade day: the upload date or one of the 3 weekdays before it, whichever puts
the most fills on a print (price +-$0.005, time -1 s..+2 s). Reported per video: day chosen, fills, hits, mean chance
(share of 3-second windows within +-30 min holding a print at that price). Picking the best of 4 days inflates hits a
little; the chance column is for one day, so compare hits to chance x fills with that in mind.
Data engineering only, no returns.
  python research/analysis/scripts/ross_lightspeed_log_check.py
"""
import glob
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ross_exec_size_pilot import ticks_sz  # noqa: E402
from backfill_ross_ledger import ET, _client  # noqa: E402

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs', 'ross_imitation', 'lightspeed_logs')
MAP = r'C:\Repositories\Stock-Picker\Ross Cameron Day Trading Videos\extractions\file_video_id_map.json'
TOL = 0.005


def lev1(a, b):
    """True if a and b differ by at most one substitution/insertion/deletion."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    s, l = sorted((a, b), key=len)
    return any(l[:i] + l[i + 1:] == s for i in range(len(l)))


def consolidate(f):
    """OCR reads each log row many times with small errors. Snap symbols to the video's common symbols (>= 5 rows,
    edit distance 1), then keep (time, symbol, price, filled) keys read at least twice, or the only key read for
    that (time, symbol)."""
    cnt = f.symbol.value_counts()
    real = []
    for s in cnt.index:  # most common first; a symbol one edit away from a more common one is a misread
        if cnt[s] >= 5 and not any(lev1(s, r) for r in real):
            real.append(s)
    f = f.copy()
    f['symbol'] = f.symbol.map(lambda s: s if s in real else next((r for r in real if lev1(s, r)), s))
    # same time, price and quantity under different symbols = one fill misread; keep the video's commoner symbol
    f['w'] = f.symbol.map(cnt)
    win = f.sort_values('w', ascending=False).groupby(['time', 'price', 'filled']).symbol.first()
    f = f.merge(win.rename('win').reset_index(), on=['time', 'price', 'filled'])
    f = f[(f.symbol == f.win) & f.symbol.isin(real)].drop(columns=['w', 'win'])
    # same second, price within 3%, different symbol = misread ghost of the commoner symbol's row
    f['w'] = f.symbol.map(cnt)
    ghost = []
    for _, g in f.groupby('time'):
        if g.symbol.nunique() < 2:
            continue
        top = g.loc[g.w.idxmax(), 'symbol']
        for i, r in g[g.symbol != top].iterrows():
            if (abs(g[g.symbol == top].price - r.price) <= 0.03 * r.price).any():
                ghost.append(i)
    f = f.drop(index=ghost).drop(columns=['w'])
    k = f.groupby(['time', 'symbol', 'price', 'filled']).size().rename('n').reset_index()
    best = k.groupby(['time', 'symbol']).n.transform('max')
    keep = k[(k.n >= 2) | ((k.n == best) & (k.groupby(['time', 'symbol']).n.transform('size') == 1))]
    side = f.groupby(['time', 'symbol', 'price', 'filled']).side.agg(lambda s: s.dropna().mode().iat[0] if s.dropna().size else '')
    return keep.merge(side.reset_index(), on=['time', 'symbol', 'price', 'filled'])


def score(client, fills, d):
    base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
    hits, chances = [], []
    for _, r in fills.iterrows():
        tz = ticks_sz(client, r.symbol, d)
        if tz is None or not len(tz[0]):
            hits.append(False); chances.append(np.nan); continue
        tt, pp, _ = tz
        h, m, s = map(int, r.time.split(':'))
        ts = base + h * 3600 + m * 60 + s
        at = np.abs(pp - r.price) <= TOL
        hits.append(bool((at & (tt >= ts - 1) & (tt < ts + 3)).any()))
        w = np.floor((tt[at] - (ts - 1800)) / 3).astype(int)
        chances.append(len(np.unique(w[(w >= 0) & (w < 1200)])) / 1200)
    return hits, chances


def main():
    up = {v['video_id']: v['upload_date'] for v in json.load(open(MAP)).values() if v and v.get('video_id')}
    client = _client()
    out, rows = [], []
    for p in sorted(glob.glob(os.path.join(D, '*.csv'))):
        vid = os.path.basename(p)[:-4]
        if vid == 'check' or vid not in up:
            continue
        f = pd.read_csv(p)
        f = f[f.filled > 0]
        raw = len(f)
        f = consolidate(f) if len(f) else f
        print(f'{vid}: {raw} raw rows -> {len(f)} consolidated fills', flush=True)
        if f.empty:
            continue
        d0 = datetime.strptime(str(up[vid]), '%Y%m%d').date()
        days = [d0] + [d0 - timedelta(days=k) for k in range(1, 6) if (d0 - timedelta(days=k)).weekday() < 5][:3]
        best = max(((d,) + score(client, f, d) for d in days), key=lambda x: sum(x[1]))
        d, hits, ch = best
        out.append(dict(video_id=vid, upload=d0, day=d, fills=len(f), hits=sum(hits), chance=np.nanmean(ch)))
        rows += [dict(video_id=vid, day=d, **r._asdict() if hasattr(r, '_asdict') else r.to_dict(), hit=h, chance=c)
                 for (_, r), h, c in zip(f.iterrows(), hits, ch)]
    r = pd.DataFrame(out)
    pd.DataFrame(rows).to_csv(os.path.join(D, 'check.csv'), index=False)
    print(r.to_string())
    if len(r):
        print(f'TOTAL fills {r.fills.sum()} hits {r.hits.sum()} ({r.hits.sum() / r.fills.sum():.0%}) '
              f'mean chance {r.chance.mean():.1%}')


if __name__ == '__main__':
    main()
