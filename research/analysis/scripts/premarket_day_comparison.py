#!/usr/bin/env python3
"""
Pre-Market Day Type Analysis
Compares pre-market conditions on EASY days vs TRAP days.

Data sources:
  - stock_candles_1d: prior day close (time column, 05:00 UTC = midnight ET)
  - stock_candles_1m: premarket bars (09:00-14:30 UTC = 4am-9:30am ET)
  - stock_fundamentals: float_shares, market_cap
  - optimizer/robust_results.db: day classifications from 186 trial configs
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import sqlite3
import psycopg2
import psycopg2.extras
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import statistics
import csv

OPTIMIZER_DB = os.path.join(os.path.dirname(__file__), '..', 'optimizer', 'robust_results.db')
TSDB_CONN = 'postgresql://postgres:changeme123@localhost:5432/stockdata'
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), 'premarket_day_features.csv')


def classify_days():
    """Classify each trading day as EASY/TRAP/SKILL/MIXED based on config profitability."""
    conn = sqlite3.connect(OPTIMIZER_DB)
    cursor = conn.cursor()
    cursor.execute('SELECT date, run_id, SUM(pnl) as day_pnl FROM trades GROUP BY date, run_id')
    rows = cursor.fetchall()
    conn.close()

    day_data = defaultdict(list)
    for date, run_id, day_pnl in rows:
        day_data[date].append(day_pnl)

    day_classes = {}
    for date, pnls in sorted(day_data.items()):
        n = len(pnls)
        n_prof = sum(1 for p in pnls if p > 0)
        pct = n_prof / n if n > 0 else 0

        if n < 3:
            cls = 'DEAD'
        elif pct >= 0.60:
            cls = 'EASY'
        elif pct <= 0.30:
            cls = 'TRAP'
        elif 0.40 <= pct <= 0.60:
            cls = 'SKILL'
        else:
            cls = 'MIXED'

        day_classes[date] = {
            'class': cls, 'n_configs': n, 'pct_profitable': pct,
            'avg_pnl': sum(pnls) / len(pnls),
            'best_pnl': max(pnls), 'worst_pnl': min(pnls),
        }
    return day_classes


def compute_day_features(cursor, date_str):
    """
    Compute all pre-market features for one trading day.

    Approach:
    1. Get prior day's close for each symbol from stock_candles_1d
    2. Get premarket 1m bars (09:00-14:25 UTC = 4am-9:25am ET)
    3. Compute gap%, PM volume, PM range, etc. per symbol
    4. Filter to gappers (up 10%+) and aggregate
    """
    features = {}

    # The daily candle timestamp is 05:00 UTC for the trading day.
    # Prior trading day close: we need the most recent daily candle BEFORE this date.
    # Current day in daily_candles format: date at 05:00 UTC

    # Step 1: Find gappers using a single efficient query
    # Join prior day close with premarket high/close to find stocks gapping 10%+
    cursor.execute("""
        WITH prior_close AS (
            SELECT DISTINCT ON (symbol) symbol, close as prev_close
            FROM stock_candles_1d
            WHERE time < %s::date + interval '5 hours'
              AND time >= %s::date - interval '5 days'
            ORDER BY symbol, time DESC
        ),
        pm_bars AS (
            SELECT symbol,
                   MIN(open) FILTER (WHERE time = (
                       SELECT MIN(time) FROM stock_candles_1m m2
                       WHERE m2.symbol = stock_candles_1m.symbol
                         AND m2.time >= %s::date + interval '9 hours'
                         AND m2.time < %s::date + interval '14 hours 25 minutes'
                   )) as pm_open,
                   MAX(high) as pm_high,
                   MIN(low) as pm_low,
                   SUM(volume) as pm_volume,
                   COUNT(*) as bar_count
            FROM stock_candles_1m
            WHERE time >= %s::date + interval '9 hours'
              AND time < %s::date + interval '14 hours 25 minutes'
            GROUP BY symbol
            HAVING SUM(volume) > 0
        )
        SELECT pc.symbol, pc.prev_close, pb.pm_open, pb.pm_high, pb.pm_low,
               pb.pm_volume, pb.bar_count
        FROM prior_close pc
        JOIN pm_bars pb ON pc.symbol = pb.symbol
        WHERE pc.prev_close > 0
    """, (date_str, date_str, date_str, date_str, date_str, date_str))

    all_stocks = cursor.fetchall()
    if not all_stocks:
        return None

    # Calculate gap % and filter to gappers (10%+)
    gappers = []
    all_gap_pcts = []
    for row in all_stocks:
        symbol, prev_close, pm_open, pm_high, pm_low, pm_volume, bar_count = row
        if prev_close and prev_close > 0 and pm_high:
            # Use PM high as the "gap" reference (most generous interpretation)
            gap_pct = (float(pm_high) - float(prev_close)) / float(prev_close) * 100
            all_gap_pcts.append(gap_pct)
            if gap_pct >= 10:
                gappers.append({
                    'symbol': symbol,
                    'prev_close': float(prev_close),
                    'pm_open': float(pm_open) if pm_open else None,
                    'pm_high': float(pm_high),
                    'pm_low': float(pm_low),
                    'pm_volume': int(pm_volume),
                    'gap_pct': gap_pct,
                    'bar_count': bar_count,
                })

    features['n_gappers'] = len(gappers)
    features['n_total_stocks_trading_pm'] = len(all_stocks)

    if len(gappers) == 0:
        return features  # Return with just n_gappers=0

    # ── Gap % metrics ─────────────────────────────────────────────────────
    gaps = [g['gap_pct'] for g in gappers]
    features['avg_gap_pct'] = statistics.mean(gaps)
    features['max_gap_pct'] = max(gaps)
    features['median_gap_pct'] = statistics.median(gaps)
    features['gap_spread'] = max(gaps) - min(gaps) if len(gaps) > 1 else 0
    features['n_gap_20plus'] = sum(1 for g in gaps if g >= 20)
    features['n_gap_50plus'] = sum(1 for g in gaps if g >= 50)
    features['n_gap_100plus'] = sum(1 for g in gaps if g >= 100)

    # ── Volume metrics ────────────────────────────────────────────────────
    volumes = [g['pm_volume'] for g in gappers]
    features['total_pm_volume'] = sum(volumes)
    features['avg_pm_volume'] = statistics.mean(volumes)
    features['median_pm_volume'] = statistics.median(volumes)
    features['max_pm_volume'] = max(volumes)
    features['n_vol_100k'] = sum(1 for v in volumes if v >= 100_000)
    features['n_vol_500k'] = sum(1 for v in volumes if v >= 500_000)
    features['n_vol_1m'] = sum(1 for v in volumes if v >= 1_000_000)
    # Volume concentration
    features['vol_concentration_top1'] = max(volumes) / sum(volumes) if sum(volumes) > 0 else 0
    top2 = sum(sorted(volumes, reverse=True)[:2])
    features['vol_concentration_top2'] = top2 / sum(volumes) if sum(volumes) > 0 else 0

    # ── Price metrics ─────────────────────────────────────────────────────
    prices = [g['prev_close'] for g in gappers if g['prev_close'] > 0]
    if prices:
        features['avg_price'] = statistics.mean(prices)
        features['median_price'] = statistics.median(prices)
        features['n_under_5'] = sum(1 for p in prices if p < 5)
        features['n_5_to_10'] = sum(1 for p in prices if 5 <= p < 10)
        features['n_10_to_20'] = sum(1 for p in prices if 10 <= p <= 20)
        features['n_over_20'] = sum(1 for p in prices if p > 20)

    # ── PM range (volatility) ────────────────────────────────────────────
    ranges = []
    for g in gappers:
        if g['pm_high'] and g['pm_low'] and g['prev_close'] > 0:
            r = (g['pm_high'] - g['pm_low']) / g['prev_close'] * 100
            ranges.append(r)
    if ranges:
        features['avg_pm_range_pct'] = statistics.mean(ranges)
        features['max_pm_range_pct'] = max(ranges)
        features['median_pm_range_pct'] = statistics.median(ranges)

    # ── PM fade: how many gave back >50% of PM gains ─────────────────────
    # Need PM close (last bar before 9:25am)
    symbols = [g['symbol'] for g in gappers]
    if symbols:
        placeholders = ','.join(['%s'] * len(symbols))
        cursor.execute(f"""
            SELECT DISTINCT ON (symbol) symbol, close as pm_close
            FROM stock_candles_1m
            WHERE symbol IN ({placeholders})
              AND time >= %s::date + interval '9 hours'
              AND time < %s::date + interval '14 hours 25 minutes'
            ORDER BY symbol, time DESC
        """, symbols + [date_str, date_str])
        pm_closes = {r[0]: float(r[1]) for r in cursor.fetchall()}

        fades = 0
        holding = 0
        for g in gappers:
            sym = g['symbol']
            if sym in pm_closes and g['pm_high'] and g['prev_close']:
                pm_close = pm_closes[sym]
                pm_gain = g['pm_high'] - g['prev_close']
                current_gain = pm_close - g['prev_close']
                if pm_gain > 0:
                    fade_pct = 1 - (current_gain / pm_gain)
                    if fade_pct > 0.5:
                        fades += 1
                    else:
                        holding += 1

        features['n_faded'] = fades
        features['n_holding'] = holding
        features['pct_faded'] = fades / len(gappers) if len(gappers) > 0 else 0

    # ── Volume acceleration: last 30min vs first 30min of PM ─────────────
    if symbols:
        placeholders = ','.join(['%s'] * len(symbols))

        # Early PM: 4:00-4:30 ET = 09:00-09:30 UTC
        cursor.execute(f"""
            SELECT SUM(volume) FROM stock_candles_1m
            WHERE symbol IN ({placeholders})
              AND time >= %s::date + interval '9 hours'
              AND time < %s::date + interval '9 hours 30 minutes'
        """, symbols + [date_str, date_str])
        early_vol = cursor.fetchone()[0] or 0

        # Late PM: 8:55-9:25 ET = 13:55-14:25 UTC
        cursor.execute(f"""
            SELECT SUM(volume) FROM stock_candles_1m
            WHERE symbol IN ({placeholders})
              AND time >= %s::date + interval '13 hours 55 minutes'
              AND time < %s::date + interval '14 hours 25 minutes'
        """, symbols + [date_str, date_str])
        late_vol = cursor.fetchone()[0] or 0

        features['early_pm_volume'] = int(early_vol)
        features['late_pm_volume'] = int(late_vol)
        features['pm_vol_acceleration'] = float(late_vol) / float(early_vol) if early_vol > 0 else 0

    # ── Late PM trend: price direction 9:00-9:25am ET ────────────────────
    if symbols:
        placeholders = ','.join(['%s'] * len(symbols))
        cursor.execute(f"""
            WITH early AS (
                SELECT DISTINCT ON (symbol) symbol, close as price_early
                FROM stock_candles_1m
                WHERE symbol IN ({placeholders})
                  AND time >= %s::date + interval '13 hours'
                  AND time < %s::date + interval '13 hours 5 minutes'
                ORDER BY symbol, time
            ),
            late AS (
                SELECT DISTINCT ON (symbol) symbol, close as price_late
                FROM stock_candles_1m
                WHERE symbol IN ({placeholders})
                  AND time >= %s::date + interval '14 hours 20 minutes'
                  AND time < %s::date + interval '14 hours 26 minutes'
                ORDER BY symbol, time DESC
            )
            SELECT e.symbol, e.price_early, l.price_late
            FROM early e JOIN late l ON e.symbol = l.symbol
            WHERE e.price_early > 0
        """, symbols + [date_str, date_str] + symbols + [date_str, date_str])

        late_changes = []
        for r in cursor.fetchall():
            chg = (float(r[2]) - float(r[1])) / float(r[1]) * 100
            late_changes.append(chg)

        if late_changes:
            features['avg_late_pm_trend'] = statistics.mean(late_changes)
            features['n_trending_up_late'] = sum(1 for c in late_changes if c > 0)
            features['n_fading_late'] = sum(1 for c in late_changes if c < -1)
            features['pct_trending_up'] = features['n_trending_up_late'] / len(late_changes) if late_changes else 0

    # ── Fundamentals ─────────────────────────────────────────────────────
    if symbols:
        placeholders = ','.join(['%s'] * len(symbols))
        cursor.execute(f"""
            SELECT symbol, float_shares, market_cap FROM stock_fundamentals
            WHERE symbol IN ({placeholders})
        """, symbols)
        fund = {r[0]: (r[1], r[2]) for r in cursor.fetchall()}

        floats = [float(fund[s][0]) for s in symbols if s in fund and fund[s][0] and fund[s][0] > 0]
        mcaps = [float(fund[s][1]) for s in symbols if s in fund and fund[s][1] and fund[s][1] > 0]

        if floats:
            features['avg_float'] = statistics.mean(floats)
            features['median_float'] = statistics.median(floats)
            features['n_float_under_10m'] = sum(1 for f in floats if f < 10_000_000)
            features['n_float_under_20m'] = sum(1 for f in floats if f < 20_000_000)
            features['pct_low_float'] = features['n_float_under_10m'] / len(gappers)

        if mcaps:
            features['avg_mcap'] = statistics.mean(mcaps)
            features['median_mcap'] = statistics.median(mcaps)
            features['n_mcap_under_100m'] = sum(1 for m in mcaps if m < 100_000_000)
            features['n_mcap_under_500m'] = sum(1 for m in mcaps if m < 500_000_000)

    # ── SPY/QQQ gap and range ────────────────────────────────────────────
    for idx in ['SPY', 'QQQ']:
        cursor.execute("""
            SELECT open, high, low, close FROM stock_candles_1d
            WHERE symbol = %s AND time >= %s::date + interval '5 hours'
              AND time < %s::date + interval '29 hours'
            LIMIT 1
        """, (idx, date_str, date_str))
        today = cursor.fetchone()

        cursor.execute("""
            SELECT close FROM stock_candles_1d
            WHERE symbol = %s AND time < %s::date + interval '5 hours'
            ORDER BY time DESC LIMIT 1
        """, (idx, date_str))
        prev = cursor.fetchone()

        if today and prev and prev[0] and prev[0] > 0:
            features[f'{idx.lower()}_gap_pct'] = (float(today[0]) - float(prev[0])) / float(prev[0]) * 100
        if today and today[0] and today[0] > 0:
            features[f'{idx.lower()}_range_pct'] = (float(today[1]) - float(today[2])) / float(today[0]) * 100

    # ── Day of week ──────────────────────────────────────────────────────
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    features['day_of_week'] = dt.weekday()  # 0=Mon, 4=Fri

    return features


def main():
    print("=" * 70)
    print("  PRE-MARKET DAY TYPE ANALYSIS")
    print("=" * 70)

    # Classify days
    print("\n[1/3] Classifying trading days...")
    day_classes = classify_days()
    counts = Counter(d['class'] for d in day_classes.values())
    for cls in ['EASY', 'TRAP', 'SKILL', 'MIXED', 'DEAD']:
        print(f"  {cls}: {counts.get(cls, 0)} days")

    # Query pre-market features
    print(f"\n[2/3] Computing pre-market features for {len(day_classes)} dates...")
    tsdb = psycopg2.connect(TSDB_CONN, connect_timeout=10)
    tsdb.set_session(autocommit=True)

    all_features = {}
    dates = sorted(day_classes.keys())
    for i, date_str in enumerate(dates):
        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{i+1}/{len(dates)}] {date_str}...")
        try:
            feat = compute_day_features(tsdb.cursor(), date_str)
            if feat and feat.get('n_gappers', 0) > 0:
                all_features[date_str] = feat
        except Exception as e:
            print(f"  ERROR on {date_str}: {e}")

    tsdb.close()
    print(f"  Got features for {len(all_features)} / {len(dates)} dates")

    # Collect all feature names
    all_names = set()
    for f in all_features.values():
        all_names.update(f.keys())
    all_names = sorted(all_names)

    # Write CSV
    header = ['date', 'day_class', 'pct_profitable', 'avg_pnl', 'n_configs'] + all_names
    rows_written = 0
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for date in sorted(all_features.keys()):
            dc = day_classes[date]
            feat = all_features[date]
            row = [date, dc['class'], f"{dc['pct_profitable']:.3f}",
                   f"{dc['avg_pnl']:.2f}", dc['n_configs']]
            for name in all_names:
                val = feat.get(name, '')
                if isinstance(val, float):
                    row.append(f"{val:.4f}")
                else:
                    row.append(val)
            writer.writerow(row)
            rows_written += 1

    print(f"\n[3/3] Wrote {rows_written} rows × {len(all_names)} features to {OUTPUT_CSV}")

    # ── COMPARISON ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  EASY vs TRAP DAY COMPARISON")
    print("=" * 70)

    easy = {d: all_features[d] for d in all_features if day_classes[d]['class'] == 'EASY'}
    trap = {d: all_features[d] for d in all_features if day_classes[d]['class'] == 'TRAP'}
    print(f"\n  EASY days with data: {len(easy)}")
    print(f"  TRAP days with data: {len(trap)}")

    metrics = [
        ('n_gappers', 'Number of gappers (10%+)'),
        ('avg_gap_pct', 'Average gap %'),
        ('max_gap_pct', 'Max gap % (hottest)'),
        ('median_gap_pct', 'Median gap %'),
        ('gap_spread', 'Gap spread (max-min)'),
        ('n_gap_20plus', 'Gappers 20%+'),
        ('n_gap_50plus', 'Gappers 50%+'),
        ('total_pm_volume', 'Total PM volume'),
        ('avg_pm_volume', 'Avg PM volume/gapper'),
        ('median_pm_volume', 'Median PM volume'),
        ('max_pm_volume', 'Max PM volume'),
        ('n_vol_100k', 'Stocks with PM vol>100K'),
        ('n_vol_500k', 'Stocks with PM vol>500K'),
        ('n_vol_1m', 'Stocks with PM vol>1M'),
        ('vol_concentration_top1', 'Vol concentration (top1)'),
        ('vol_concentration_top2', 'Vol concentration (top2)'),
        ('avg_price', 'Avg prior close price'),
        ('n_under_5', 'Gappers under $5'),
        ('n_5_to_10', 'Gappers $5-$10'),
        ('n_10_to_20', 'Gappers $10-$20'),
        ('avg_pm_range_pct', 'Avg PM range %'),
        ('max_pm_range_pct', 'Max PM range %'),
        ('pct_faded', '% faded >50%'),
        ('n_faded', 'Count faded'),
        ('n_holding', 'Count holding gains'),
        ('pm_vol_acceleration', 'PM vol acceleration'),
        ('early_pm_volume', 'Early PM vol (4-4:30)'),
        ('late_pm_volume', 'Late PM vol (8:55-9:25)'),
        ('avg_late_pm_trend', 'Late PM trend (9-9:25 %)'),
        ('pct_trending_up', '% trending up late PM'),
        ('avg_float', 'Avg float'),
        ('median_float', 'Median float'),
        ('pct_low_float', '% low float (<10M)'),
        ('avg_mcap', 'Avg market cap'),
        ('n_mcap_under_100m', 'Gappers mcap<$100M'),
        ('spy_gap_pct', 'SPY gap %'),
        ('spy_range_pct', 'SPY daily range %'),
        ('qqq_gap_pct', 'QQQ gap %'),
        ('day_of_week', 'Day of week (0=Mon)'),
    ]

    print(f"\n{'Metric':<30} {'EASY':>12} {'TRAP':>12} {'Diff%':>8} {'Signal':>8}")
    print("-" * 72)

    for key, label in metrics:
        e_vals = [f[key] for f in easy.values() if key in f and f[key] is not None]
        t_vals = [f[key] for f in trap.values() if key in f and f[key] is not None]
        if not e_vals or not t_vals:
            continue

        e_avg = statistics.mean(e_vals)
        t_avg = statistics.mean(t_vals)
        diff = ((t_avg - e_avg) / abs(e_avg) * 100) if e_avg != 0 else 0
        sig = "***" if abs(diff) > 30 else "**" if abs(diff) > 20 else "*" if abs(diff) > 10 else ""

        if abs(e_avg) > 1_000_000:
            print(f"  {label:<28} {e_avg:>10,.0f} {t_avg:>10,.0f} {diff:>+7.0f}% {sig}")
        elif abs(e_avg) > 100:
            print(f"  {label:<28} {e_avg:>10,.1f} {t_avg:>10,.1f} {diff:>+7.0f}% {sig}")
        elif abs(e_avg) > 1:
            print(f"  {label:<28} {e_avg:>10.2f} {t_avg:>10.2f} {diff:>+7.0f}% {sig}")
        else:
            print(f"  {label:<28} {e_avg:>10.3f} {t_avg:>10.3f} {diff:>+7.0f}% {sig}")


if __name__ == '__main__':
    main()
