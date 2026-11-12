"""Pilot: pin Ross Cameron's narrated executions to the second using tick (trade) data.

Input:  research/analysis/outputs/ross_imitation/executions_pilot.jsonl  (Sonnet extraction of 50 transcripts:
        ordered executions per ticker with stated price/shares/action, no timestamps)
Output: research/analysis/outputs/ross_imitation/match_pilot.csv  + printed summary

Method (data engineering only, no returns are computed):
  1. Candidate trade days per (video, ticker): the upload date and the 4 weekdays before it.
  2. Tick trades (Alpaca SIP, free historical) for that ticker/day, 04:00-11:30 ET, cached locally.
  3. Priced executions in narrated order must happen in time order. A print "matches" an execution if
     |print price - stated price| <= tol = max($0.02, 0.15% of price).
     Forward pass: earliest feasible time e_i = first matching print at or after e_{i-1}.
     Backward pass: latest feasible time l_i = last matching print at or before l_{i+1}.
     A day is feasible if e_i <= l_i for every execution. The chosen day = feasible day closest to upload date.
  4. Inside [e_i, l_i], matching prints are grouped into episodes (gap > 5 s starts a new episode).
     Pinned <= 5 s: exactly one episode and it lasts <= 5 s. Also reported: <= 30 s, <= 60 s, episode counts.
     A stated clock time (e.g. "8:00 a.m.") narrows the window to +/- 2 minutes when it parses.
Usage:
  python research/analysis/scripts/ross_exec_match_pilot.py            # fetch (cached) + match + summary
"""
import json
import os
import pickle
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, _client  # noqa: E402

from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.requests import StockTradesRequest  # noqa: E402

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'ross_imitation'))
CACHE = os.path.join(OUT, 'ticks')
N_DAYS = 5
GAP_S = 5.0
WIN = ((4, 0), (11, 30))
MIN_TOL, REL_TOL = 0.02, 0.0015


def candidate_days(upload):
    d = datetime.strptime(upload, '%Y%m%d').date()
    out = []
    while len(out) < N_DAYS:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def ticks(client, sym, d):
    """(epoch seconds float array, price array) for sym on day d, 04:00-11:30 ET. Cached."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'{sym}_{d:%Y%m%d}.pkl')
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    s = ET.localize(datetime(d.year, d.month, d.day, *WIN[0]))
    e = ET.localize(datetime(d.year, d.month, d.day, *WIN[1]))
    data = None
    for attempt in range(6):
        try:
            data = client.get_stock_trades(StockTradesRequest(symbol_or_symbols=sym, start=s, end=e,
                                                              feed=DataFeed.SIP)).data.get(sym, [])
            break
        except Exception as ex:  # noqa: BLE001
            msg = str(ex)
            if 'invalid symbol' in msg.lower() or 'not found' in msg.lower():
                data = []
                break
            time.sleep(2 ** attempt * (5 if '429' in msg else 1))
    if data is None:
        return None
    t = np.array([x.timestamp.timestamp() for x in data], float)
    p = np.array([x.price for x in data], float)
    pickle.dump((t, p), open(path, 'wb'))
    return t, p


def parse_clock(s, d):
    """Epoch seconds for a stated clock time like '8:00 a.m.' / '7:02am' / '9:31'; None if not parseable.
    'open'/'bell' -> 09:30."""
    if not s:
        return None
    low = s.lower()
    m = re.search(r'\b(\d{1,2}):(\d{2})\s*(a\.?m\.?|p\.?m\.?)?', low)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if m.group(3) and m.group(3).startswith('p') and h < 12:
            h += 12
        if not (4 <= h <= 11):
            return None
    elif re.search(r'\bopen\b|\bbell\b', low):
        h, mi = 9, 30
    else:
        m = re.search(r'\b(\d{1,2})\s*(a\.?m\.?)', low)
        if not m:
            return None
        h, mi = int(m.group(1)), 0
        if not (4 <= h <= 11):
            return None
    return ET.localize(datetime(d.year, d.month, d.day, h, mi)).timestamp()


def match_day(execs, t, p, d):
    """Forward/backward feasibility. Returns list of per-exec dicts, or None if infeasible."""
    n = len(execs)
    masks = []
    for x in execs:
        tol = max(MIN_TOL, REL_TOL * x['price'])
        m = np.abs(p - x['price']) <= tol
        ct = parse_clock(x.get('clock_time'), d)
        if ct is not None:
            m &= (t >= ct - 120) & (t <= ct + 120)
        masks.append(m)
    e = [None] * n
    lo = -np.inf
    for i in range(n):
        idx = np.where(masks[i] & (t >= lo))[0]
        if not len(idx):
            return None
        e[i] = t[idx[0]]
        lo = e[i]
    l_ = [None] * n
    hi = np.inf
    for i in range(n - 1, -1, -1):
        idx = np.where(masks[i] & (t <= hi))[0]
        if not len(idx):
            return None
        l_[i] = t[idx[-1]]
        hi = l_[i]
    res = []
    for i in range(n):
        if e[i] > l_[i]:
            return None
        tt = t[masks[i] & (t >= e[i]) & (t <= l_[i])]
        breaks = np.where(np.diff(tt) > GAP_S)[0]
        starts = np.r_[tt[0], tt[breaks + 1]]
        ends = np.r_[tt[breaks], tt[-1]]
        dur = ends - starts
        res.append(dict(est=e[i], lo=e[i], hi=l_[i], window_s=l_[i] - e[i], episodes=len(starts),
                        first_episode_s=float(dur[0]), n_prints=len(tt)))
    return res


def main():
    rows = [json.loads(x) for x in open(os.path.join(OUT, 'executions_pilot.jsonl'), encoding='utf-8')]
    ex = [r for r in rows if not r.get('no_executions')]
    groups = defaultdict(list)
    for r in ex:
        groups[(r['file_no'], (r.get('ticker') or '').upper().strip(), r['upload_date'])].append(r)
    client = _client()
    out, gsum = [], []
    for gi, ((fno, sym, up), g) in enumerate(sorted(groups.items()), 1):
        print(f'  group {gi}/{len(groups)} {fno} {sym}', flush=True)
        g = sorted(g, key=lambda r: (r.get('seq') or 0))
        priced = [r for r in g if r.get('price') and r.get('price_confidence') in ('high', 'medium')]
        info = dict(file_no=fno, ticker=sym, upload=up, execs=len(g), priced=len(priced))
        if not sym.isalpha() or not priced:
            info['status'] = 'no ticker' if not sym.isalpha() else 'no priced execs'
            gsum.append(info)
            continue
        feas = []
        for d in candidate_days(up):
            tp = ticks(client, sym, d)
            if tp is None or not len(tp[0]):
                continue
            res = match_day(priced, tp[0], tp[1], d)
            if res is not None:
                feas.append((d, res))
        info['feasible_days'] = len(feas)
        if not feas:
            info['status'] = 'no feasible day'
            gsum.append(info)
            continue
        d, res = feas[0]   # closest to upload date
        info['status'] = 'matched'
        info['day'] = d
        gsum.append(info)
        for x, m in zip(priced, res):
            out.append(dict(file_no=fno, ticker=sym, day=d, seq=x.get('seq'), action=x.get('action'),
                            price=x['price'], conf=x['price_confidence'], shares=x.get('shares'),
                            est_time=datetime.fromtimestamp(m['est'], ET).strftime('%H:%M:%S'),
                            window_s=round(m['window_s'], 1), episodes=m['episodes'],
                            first_episode_s=round(m['first_episode_s'], 1), n_prints=m['n_prints'],
                            feasible_days=len(feas), clock_time=x.get('clock_time')))
    df = pd.DataFrame(out)
    gs = pd.DataFrame(gsum)
    df.to_csv(os.path.join(OUT, 'match_pilot.csv'), index=False)
    gs.to_csv(os.path.join(OUT, 'match_pilot_groups.csv'), index=False)

    print(f'videos {len({r["file_no"] for r in rows})} | execution rows {len(ex)} | ticker groups {len(gs)}')
    print('group status:', gs.status.value_counts().to_dict())
    if 'feasible_days' in gs:
        fd = gs[gs.status == 'matched'].feasible_days.value_counts().sort_index().to_dict()
        print('matched groups by number of feasible candidate days (1 = day unambiguous):', fd)
    if len(df):
        n = len(df)
        one = df.episodes == 1
        print(f'priced executions placed in time: {n} (of {sum(1 for r in ex if r.get("price"))} with any price)')
        for lim in (5, 30, 60):
            k = int((one & (df.window_s <= lim)).sum())
            k2 = int((one & (df.first_episode_s <= lim)).sum())
            print(f'  one episode, whole feasible window <= {lim:>2}s: {k:>4} ({k / n:.0%}) | '
                  f'one episode lasting <= {lim:>2}s: {k2:>4} ({k2 / n:.0%})')
        print('  episodes per execution: median', int(df.episodes.median()), '| p75', int(df.episodes.quantile(.75)))
        u = df[df.feasible_days == 1]
        if len(u):
            print(f'  same, only groups whose day is unambiguous ({len(u)} execs): one-episode <= 5s '
                  f'{int(((u.episodes == 1) & (u.first_episode_s <= 5)).sum())}, median episodes {int(u.episodes.median())}')
    print('DONE')


if __name__ == '__main__':
    main()
