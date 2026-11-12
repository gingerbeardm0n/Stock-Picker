"""Pilot step 2: can Ross's large orders be found in the tape by size?

Uses the day and feasible time window per execution from ross_exec_match_pilot.py (match_pilot.csv), refetches
that day's ticks WITH trade sizes, and looks for "bursts": prints within the price tolerance inside a 1-second
bucket whose summed size is at least half of the shares he says he traded.
  pinned  = exactly one such burst second in the feasible window
Reported for executions with a stated share count >= 1,000 (smaller orders do not stand out).
Data engineering only, no returns.
  python research/analysis/scripts/ross_exec_size_pilot.py
"""
import os
import pickle
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, _client  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from ross_exec_match_pilot import MIN_TOL, REL_TOL, OUT, WIN  # noqa: E402

from alpaca.data.enums import DataFeed  # noqa: E402
from alpaca.data.requests import StockTradesRequest  # noqa: E402

CACHE = os.path.join(OUT, 'ticks_sz')
MIN_SHARES = 1000
FRAC = 0.5


def ticks_sz(client, sym, d):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f'{sym}_{d:%Y%m%d}.pkl')
    if os.path.exists(path):
        return pickle.load(open(path, 'rb'))
    s = ET.localize(datetime(d.year, d.month, d.day, *WIN[0]))
    e = ET.localize(datetime(d.year, d.month, d.day, *WIN[1]))
    for attempt in range(6):
        try:
            data = client.get_stock_trades(StockTradesRequest(symbol_or_symbols=sym, start=s, end=e,
                                                              feed=DataFeed.SIP)).data.get(sym, [])
            break
        except Exception as ex:  # noqa: BLE001
            time.sleep(2 ** attempt * (5 if '429' in str(ex) else 1))
    else:
        return None
    t = np.array([x.timestamp.timestamp() for x in data], float)
    p = np.array([x.price for x in data], float)
    z = np.array([x.size for x in data], float)
    pickle.dump((t, p, z), open(path, 'wb'))
    return t, p, z


def main():
    df = pd.read_csv(os.path.join(OUT, 'match_pilot.csv'), parse_dates=['day'])
    df['day'] = df.day.dt.date
    df = df[df.shares.fillna(0) >= MIN_SHARES].copy()
    print(f'executions with shares >= {MIN_SHARES} on a matched day: {len(df)}', flush=True)
    client = _client()
    out = []
    for (sym, d), g in df.groupby(['ticker', 'day']):
        tpz = ticks_sz(client, sym, d)
        if tpz is None:
            print(f'  fetch failed {sym} {d}', flush=True)
            continue
        t, p, z = tpz
        base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        for _, x in g.iterrows():
            est = base + sum(int(v) * m for v, m in zip(x.est_time.split(':'), (3600, 60, 1)))
            lo, hi = est, est + x.window_s
            tol = max(MIN_TOL, REL_TOL * x.price)
            m = (np.abs(p - x.price) <= tol) & (t >= lo - 1) & (t <= hi + 1)
            sec = np.floor(t[m]).astype(np.int64)
            if not len(sec):
                out.append(dict(ticker=sym, day=d, price=x.price, shares=x.shares, bursts=0)); continue
            vol = pd.Series(z[m]).groupby(sec).sum()
            big = vol[vol >= FRAC * x.shares]
            top = vol.sort_values(ascending=False)
            out.append(dict(ticker=sym, day=d, action=x.action, price=x.price, shares=int(x.shares),
                            window_s=x.window_s, bursts=len(big),
                            burst_time=(datetime.fromtimestamp(big.index[0], ET).strftime('%H:%M:%S')
                                        if len(big) == 1 else None),
                            max_sec_vol=int(top.iloc[0]), second_sec_vol=int(top.iloc[1]) if len(top) > 1 else 0))
    r = pd.DataFrame(out)
    r.to_csv(os.path.join(OUT, 'size_pilot.csv'), index=False)
    n = len(r)
    print(f'tested {n}')
    print('bursts (seconds with summed size >= half his shares) per execution:',
          r.bursts.value_counts().sort_index().to_dict())
    print(f'pinned to one second: {int((r.bursts == 1).sum())} ({(r.bursts == 1).mean():.0%})')
    print(r.to_string())
    print('DONE')


if __name__ == '__main__':
    main()
