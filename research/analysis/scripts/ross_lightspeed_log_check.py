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
