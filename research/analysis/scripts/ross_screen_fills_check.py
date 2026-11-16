"""Check screen-read fills (ross_live_video_batch.py output) against Alpaca SIP tick data.

For each video CSV: fill missing clock readings from the nearest reading's (clock - video second) offset, pick out
entries from flat (a symbol row appears, or its cost basis changes while P&L per share was 0.00: the new cost basis
is the fill price), and look for a print at that price (+-$0.005) in [t-2s, t+1s]. Chance rate = share of 4-second
windows within +-30 min that contain such a print. Trade day = upload date (checked: on 2022-02-11 it matched).
Data engineering only, no returns.
  python research/analysis/scripts/ross_screen_fills_check.py
"""
import glob
import json
import os
import sys
from datetime import date, datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ross_exec_size_pilot import ticks_sz  # noqa: E402
from backfill_ross_ledger import ET, _client  # noqa: E402

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'outputs', 'ross_imitation', 'screen_fills')
TOL = 0.005


def hms(s):
    try:
        h, m, x = map(int, s.split(':'))
        return h * 3600 + m * 60 + x if 4 <= h <= 16 else None
    except (AttributeError, ValueError):
        return None


def num(s):
    try:
        return float(str(s).replace(',', '').replace('+', ''))
    except ValueError:
        return None


def entries(df):
    df = df.copy()
    df['t'] = df.clock_after.map(hms)
    off = (df.t - df.video_sec).where(df.t.notna())
    known = df[off.notna()]
    noclock = known.empty
    out = []
    for _, r in df.iterrows():
        t = r.t
        if noclock:
            t = None
        elif np.isnan(t):
            j = (known.video_sec - r.video_sec).abs().idxmin()
            if abs(known.video_sec[j] - r.video_sec) > 120:
                continue
            t = r.video_sec + off[j]
        b, a = json.loads(r.before), json.loads(r.after)
        if not b or not a:
            continue
        for s, (px, pps, _) in a.items():
            px = num(px)
            if px is None or px <= 0:
                continue
            if s not in b:
                if len(b) >= 1 and len(a) > len(b):
                    out.append((s, px, None if t is None else int(t), 'new row', r.video_sec))
            elif num(b[s][1]) == 0 and num(b[s][0]) != px:
                out.append((s, px, None if t is None else int(t), 'from flat', r.video_sec))
    return out


def fit_offsets(ent, tick, base, tol=0.01, perms=50, seed=0):
    """No on-screen clock: find the video-second -> clock offset(s) that put the most entries on a print at their
    price. Returns {entry index: clock seconds} for entries explained by an offset found more often than chance,
    plus (best votes, 95th pct of best votes with video seconds shuffled)."""
    rng = np.random.default_rng(seed)
    cand = []
    for s, px, _, _, vs in ent:
        tt, pp = tick[s][:2]
        m = (np.abs(pp - px) <= tol + 1e-9) & (tt >= base + 6 * 3600) & (tt < base + 12 * 3600)
        cand.append(np.unique(np.floor(tt[m] - base).astype(int)))

    def best(vsecs, idx):
        votes = {}
        for i in idx:
            offs = np.unique(np.concatenate([cand[i] - vsecs[i] + d for d in (-1, 0, 1, 2)])) if len(cand[i]) else []
            for o in offs:
                votes.setdefault(int(o), set()).add(i)
        if not votes:
            return None, set()
        o = max(votes, key=lambda k: len(votes[k]))
        return o, votes[o]
    vs = np.array([e[4] for e in ent])
    left, out, first = set(range(len(ent))), {}, None
    null = []
    for _ in range(perms):
        _, hit = best(rng.permutation(vs), list(range(len(ent))))
        null.append(len(hit))
    thr = int(np.percentile(null, 95)) if null else 0
    while left:
        o, hit = best(vs, sorted(left))
        if first is None:
            first = len(hit)
        if o is None or len(hit) < max(3, thr + 1):
            break
        for i in hit:
            out[i] = int(o + vs[i])
        left -= hit
    return out, (first or 0, thr)


def main():
    client = _client()
    rows = []
    vids = pd.read_csv(os.path.join(D, 'videos_2022_live.csv'), dtype=str)
    for _, v in vids.iterrows():
        p = os.path.join(D, f'{v.video_id}.csv')
        if not os.path.exists(p):
            continue
        df = pd.read_csv(p)
        if df.empty:
            continue
        d = datetime.strptime(v.upload_date, '%Y%m%d').date()
        base = ET.localize(datetime(d.year, d.month, d.day)).timestamp()
        ent = entries(df)
        tick = {}
        for s in {e[0] for e in ent}:
            tz = ticks_sz(client, s, d)
            if tz is not None and len(tz[0]):
                tick[s] = tz
        ent = [e for e in ent if e[0] in tick]
        fitted = {}
        if ent and all(e[2] is None for e in ent):
            fitted, (bv, thr) = fit_offsets(ent, tick, base)
            print(f'  {v.video_id}: no clock, {len(ent)} entries, best offset explains {bv} (shuffled 95th pct {thr}),'
                  f' placed {len(fitted)}', flush=True)
        for k, (s, px, t, kind, vs) in enumerate(ent):
            timing = 'clock'
            if t is None:
                if k not in fitted:
                    rows.append(dict(video_id=v.video_id, day=d, sym=s, price=px, kind=kind, timing='unplaced', video_sec=vs))
                    continue
                t, timing = fitted[k], 'tick-fit'
            tt, pp, _ = tick[s]
            at = np.abs(pp - px) <= TOL
            ts = base + t
            hit = bool((at & (tt >= ts - 2) & (tt < ts + 1)).any())
            w = np.floor((tt[at] - (ts - 1800)) / 4).astype(int)
            chance = len(np.unique(w[(w >= 0) & (w < 900)])) / 900
            rows.append(dict(video_id=v.video_id, day=d, sym=s, price=px, kind=kind, timing=timing,
                             clock=f'{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}', video_sec=vs, hit=hit,
                             chance=round(chance, 3)))
    r = pd.DataFrame(rows)
    r.to_csv(os.path.join(D, 'check_entries.csv'), index=False)
    ok = r[(r.timing == 'clock') & r.hit.notna()] if 'hit' in r else r.iloc[0:0]
    print('by timing:', r.timing.value_counts().to_dict())
    print(f'videos with fills csv: {len(glob.glob(os.path.join(D, "*.csv"))) - 1 - (1 if os.path.exists(os.path.join(D, "check_entries.csv")) else 0)}'
          f' | skipped: {len(glob.glob(os.path.join(D, "*.skip")))}')
    print(f'entries checked {len(ok)} | hits {int(ok.hit.sum())} ({ok.hit.mean():.0%}) | mean chance {ok.chance.mean():.1%}'
          if len(ok) else 'no entries')
    if len(ok):
        print(ok.groupby('video_id').agg(n=('hit', 'size'), hits=('hit', 'sum'), chance=('chance', 'mean')).to_string())


if __name__ == '__main__':
    main()
