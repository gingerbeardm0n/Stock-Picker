"""Selection test: do the stocks Ross Cameron picks outperform ordinary gappers on the same day?

Follow-up to ross_oracle_entry_test.py, where buying Ross's stocks at a RANDOM minute beat
his own timing at 10-30 bars. Two hindsight leaks in that rough pass are removed here:
  1. Day choice: trade day = nearest weekday on/before the video upload date that has bars
     (not the max-volume day, which favors days the stock ran).
  2. Pick time: Ross can't pick a stock before he sees it. Entries are only taken AFTER his
     estimated entry time (first touch of his price at/after 07:00 on a >=10k-share bar),
     and never before 09:30.

Comparison group: every other gapper that day from daily_gappers with gap >= 10% and open
$1-$20 (gap% is known at the open, so no hindsight). Their bars are fetched from the same
Alpaca SIP feed into ross_gapper_bars_1m so both groups share one data source.

For each stock-day the score is the AVERAGE forward return over EVERY possible entry bar in
the window [start, 11:00) -- the expected value of a random entry -- for holds of 10 and 30
bars. Entry = next bar open, exit = close less 0.3% slippage. Both groups use the same clock
window per day (start = max(Ross's estimated pick time, 09:30)).

Day-paired difference (Ross minus gappers, same day, same window) with a bootstrap CI is the
answer: if it is clearly positive, Ross's stock selection is an edge worth modeling.

Usage:  python research/analysis/scripts/ross_selection_test.py
"""
import os
import sys
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data_backfill')))
from backfill_ross_ledger import ET, SYMBOLS_PER_REQUEST, TimeFrame, _client, _fetch, _insert  # noqa: E402
sys.path.insert(0, os.path.dirname(__file__))
from ross_oracle_entry_test import first_price  # noqa: E402

DSN = os.environ.get('STOCKDATA_DSN', 'postgresql://postgres:changeme123@localhost:5432/stockdata')
OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs'))
SLIP = 0.003
HOLDS = [10, 30]
END_MIN = 11 * 60
OPEN_MIN = 9 * 60 + 30
RNG = np.random.default_rng(20261008)


def bars_by_key(conn, table, keys=None):
    df = pd.read_sql(f"""SELECT symbol, time AT TIME ZONE 'America/New_York' AS et,
                                open, close, low, high, volume FROM {table}""", conn)
    df['d'] = df.et.dt.date
    df['mins'] = df.et.dt.hour * 60 + df.et.dt.minute
    df = df.sort_values(['symbol', 'et'])
    return {k: g.reset_index(drop=True) for k, g in df.groupby(['symbol', 'd'])}


def window_score(g, start_min):
    """Mean forward return over every entry bar in [start_min, 11:00). dict hold -> value."""
    o, c, m = g.open.values, g.close.values, g.mins.values
    n = len(o)
    sig = np.where((m >= start_min) & (m < END_MIN))[0]
    out = {}
    for h in HOLDS:
        rets = []
        for i in sig:
            e = i + 1
            j = e + h - 1
            if j < n:
                rets.append((c[j] * (1 - SLIP) - o[e]) / o[e])
        out[h] = float(np.mean(rets)) if rets else np.nan
    return out


def boot_ci(a, n=4000):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    b = RNG.choice(a, size=(n, a.size), replace=True).mean(axis=1)
    return a.size, a.mean(), np.median(a), (a > 0).mean(), np.percentile(b, 2.5), np.percentile(b, 97.5)


def line(label, s):
    n, mean, med, pos, lo, hi = s
    return (f'{label:<40} n={n:>4}  mean {mean*100:+6.2f}%  median {med*100:+6.2f}%  '
            f'pos {pos:4.0%}  95% CI [{lo*100:+.2f}, {hi*100:+.2f}]')


def main():
    conn = psycopg2.connect(DSN)
    ledger = pd.read_sql("""SELECT file_num, trade_idx, symbol, upload_date, trade_date, cells
                            FROM ross_trade_ledger WHERE status = 'matched'""", conn)
    ross_bars = bars_by_key(conn, 'ross_trade_bars_1m')

    # 1. hindsight-free trade day + estimated pick time
    picks = []
    agree = 0
    for r in ledger.itertuples():
        day = None
        for back in range(5):
            d = r.upload_date - timedelta(days=back)
            if d.weekday() < 5 and (r.symbol, d) in ross_bars:
                day = d
                break
        p = first_price(r.cells[3]) if len(r.cells) > 3 else None
        if day is None or p is None:
            continue
        agree += day == r.trade_date
        g = ross_bars[(r.symbol, day)]
        hit = np.where((g.low.values <= p) & (g.high.values >= p) & (g.mins.values >= 420)
                       & (g.volume.values >= 10_000))[0]
        if hit.size == 0:
            continue
        pick_min = int(g.mins.values[hit[0]])
        picks.append((r.symbol, day, max(pick_min, OPEN_MIN)))
    picks = pd.DataFrame(picks, columns=['symbol', 'day', 'start']).drop_duplicates(['symbol', 'day'])
    picks = picks[picks.start < END_MIN - 31]
    print(f'Ross stock-days with a pick time before 10:29: {len(picks)} '
          f'(upload-day rule agreed with max-volume day on {agree}/{len(ledger)} trades)')

    # 2. comparison gappers for those days
    days = sorted(picks.day.unique())
    gap = pd.read_sql("""SELECT trade_date, symbol, gap_pct FROM daily_gappers
                         WHERE gap_pct >= 10 AND open_price BETWEEN 1 AND 20
                           AND trade_date = ANY(%s)""", conn, params=(days,))
    ross_set = set(zip(picks.symbol, picks.day))
    in_gappers = len(ross_set & set(zip(gap.symbol, gap.trade_date)))
    gap = gap[[(s, d) not in ross_set for s, d in zip(gap.symbol, gap.trade_date)]]
    print(f'comparison gappers: {len(gap)} stock-days over {gap.trade_date.nunique()} of {len(days)} days')

    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS ross_gapper_bars_1m (LIKE ross_trade_bars_1m INCLUDING ALL)""")
        cur.execute("SELECT DISTINCT (time AT TIME ZONE 'America/New_York')::date FROM ross_gapper_bars_1m")
        have = {r[0] for r in cur.fetchall()}
    conn.commit()
    client = _client()
    todo = [d for d in sorted(gap.trade_date.unique()) if d not in have]
    print(f'fetching gapper bars for {len(todo)} days', flush=True)
    for i, d in enumerate(todo, 1):
        syms = sorted(gap[gap.trade_date == d].symbol.unique())
        start = ET.localize(datetime(d.year, d.month, d.day, 9, 0))
        end = ET.localize(datetime(d.year, d.month, d.day, 12, 0))
        for j in range(0, len(syms), SYMBOLS_PER_REQUEST):
            _insert(conn, 'ross_gapper_bars_1m', _fetch(client, syms[j:j + SYMBOLS_PER_REQUEST],
                                                        TimeFrame.Minute, start, end))
        conn.commit()
        if i % 200 == 0:
            print(f'  {i}/{len(todo)} days', flush=True)
    gap_bars = bars_by_key(conn, 'ross_gapper_bars_1m')
    conn.close()

    # 3. score both groups in the same window per day
    start_by_day = picks.groupby('day').start.min().to_dict()
    rows = []
    for p in picks.itertuples():
        s = window_score(ross_bars[(p.symbol, p.day)], p.start)
        rows.append({'group': 'ross', 'day': p.day, 'symbol': p.symbol, 'start': p.start,
                     **{f'h{h}': s[h] for h in HOLDS}})
    for gr in gap.itertuples():
        g = gap_bars.get((gr.symbol, gr.trade_date))
        if g is None or len(g) < 40:
            continue
        st = start_by_day[gr.trade_date]
        s = window_score(g, st)
        rows.append({'group': 'gapper', 'day': gr.trade_date, 'symbol': gr.symbol, 'start': st,
                     **{f'h{h}': s[h] for h in HOLDS}})
    df = pd.DataFrame(rows)
    os.makedirs(OUT, exist_ok=True)
    df.to_csv(os.path.join(OUT, 'ross_selection_scores.csv'), index=False)
    print(f'Ross picks that were also in daily_gappers (gap>=10%, $1-20): {in_gappers}/{len(ross_set)}'
          f' (excluded from the control group)')

    for h in HOLDS:
        col = f'h{h}'
        print(f'\n=== hold {h} bars, random entry after Ross\'s pick time, before 11:00 ===')
        print(line('Ross picks (per stock-day)', boot_ci(df[df.group == 'ross'][col])))
        print(line('other gappers (per stock-day)', boot_ci(df[df.group == 'gapper'][col])))
        day_mean = df.groupby(['day', 'group'])[col].mean().unstack().dropna()
        diff = day_mean['ross'] - day_mean['gapper']
        print(line('PAIRED: Ross minus gappers, same day', boot_ci(diff)))
        yr = pd.Series([d.year for d in diff.index], index=diff.index)
        for y in sorted(yr.unique()):
            sel = diff[yr == y]
            if len(sel) >= 10:
                print(line(f'  paired {y}', boot_ci(sel)))
    print('\nDONE')


if __name__ == '__main__':
    main()
