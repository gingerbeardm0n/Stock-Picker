"""EXPLORATORY follow-up to ross_entry_trigger_test.py (not pre-registered): holdout rank skill with "no" seconds
restricted to near his buy, and model score in the seconds leading up to his buy."""
import sys, os, pickle, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ross_entry_trigger_test as m
rows = pickle.load(open(os.path.join(m.CACHE, f'rows{"_lag%d" % m.LAG if m.LAG else ""}.pkl'), 'rb')).sort_values(['day','symbol','sec']).reset_index(drop=True)
rec = rows[rows.src=='recap']; days = sorted(rec.day.unique()); cut = days[int(len(days)*0.8)]
dev, hold = rec[rec.day<cut].copy(), rec[rec.day>=cut].copy()
mod = m.Model().fit(dev[m.FEATS], dev.y)
hold['score'] = mod.score(hold[m.FEATS])
def near(df, w):
    keep = []
    for (d,s), g in df.groupby(['day','symbol']):
        pos = g.sec[g.y==1].values
        dist = np.min(np.abs(g.sec.values[:,None]-pos[None,:]), axis=1)
        keep.append(g[(g.y==1) | (dist<=w)])
    return pd.concat(keep)
print('EXPLORATORY holdout rank skill, negatives restricted to near his buy:')
for w in (600, 300, 120, 60, 30, 15):
    m.report(f'no-seconds within {w}s', m.rank_skill(near(hold, w), 'score'))
# where do his seconds sit: score at t vs t-1..t-5 (does score jump AT his second? -> own-print leak?)
print('\nmean model score: his second vs seconds before/after it (holdout)')
g = hold.set_index(['day','symbol','sec']).score
pos = hold[hold.y==1][['day','symbol','sec']].values
out = {}
allrows = rec[rec.day>=cut].copy(); allrows['score']=mod.score(allrows[m.FEATS])
idx = allrows.set_index(['day','symbol','sec']).score
for k in (-30,-10,-5,-4,-3,-2,-1,0):
    v=[idx.get((d,s,t+k), np.nan) for d,s,t in pos]
    out[k]=np.nanmean(v), np.sum(~np.isnan(v))
print(' (seconds within 3s of his buys were excluded from rows, so -3..-1 mostly missing)')
for k,(a,n) in out.items(): print(f'  t{k:+d}: mean score {a:.3f} (n {n})')
print('  all no-seconds median', np.median(allrows.score[allrows.y==0]).round(3), '90th pct', np.percentile(allrows.score[allrows.y==0],90).round(3))
