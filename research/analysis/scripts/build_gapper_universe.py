#!/usr/bin/env python3
"""
Build Daily Gapper Universe
===========================
For every trading day in our date range, find stocks passing:
  Pillar 2: Up 10%+ from prior close AT ANY POINT during premarket (4am-9:30am ET)
  Pillar 3: Relative volume >= 5x (vs 30-day avg of same PM window)

Pillar 1 ($2-$20) is implicitly handled — that's the universe we collected.

Output: analysis/gapper_universe.csv
  One row per (date, symbol) that hit 10%+, with all premarket metrics.

Performance notes:
  - All UTC time arithmetic done in Python (pytz) to avoid AT TIME ZONE on 68M rows
  - PM volumes pre-loaded once for the full date range (~400K rows)
  - Per-day queries use exact UTC timestamp parameters (no server-side tz conversion)
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import psycopg2, psycopg2.extras, sqlite3, csv, statistics, pytz
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date, timezone

TSDB_CONN    = 'postgresql://postgres:changeme123@localhost:5432/stockdata'
OPTIMIZER_DB = os.path.join(os.path.dirname(__file__), '..', 'optimizer', 'robust_results.db')
OUTPUT_CSV   = os.path.join(os.path.dirname(__file__), 'gapper_universe.csv')

START_DATE   = date(2025, 1, 2)
END_DATE     = date(2026, 2, 18)
GAP_PCT_MIN  = 10.0   # Pillar 2
REL_VOL_MIN  = 5.0    # Pillar 3
RV_LOOKBACK  = 30     # trading days

ET = pytz.timezone('America/New_York')
UTC = pytz.utc


def et_to_utc(d, hour, minute):
    """Convert a date + ET hour:minute to a UTC datetime."""
    dt = ET.localize(datetime(d.year, d.month, d.day, hour, minute, 0))
    return dt.astimezone(UTC)


def get_trading_days(conn):
    """All trading days we have 1m data for."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT DATE(time) as trade_date
        FROM stock_candles_1m
        WHERE time >= %s AND time < %s
        ORDER BY trade_date
    """, (datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 2, 19, tzinfo=UTC)))
    return [r[0] for r in cursor.fetchall()]


def load_all_pm_volumes(conn):
    """
    Pre-load ALL premarket volumes for all symbols and dates.
    PM window: 4:00am - 9:25am ET (computed as UTC per-day is too complex,
    so we use 08:00-14:30 UTC which safely covers both EST and EDT seasons).
    Returns dict: {(date, symbol): pm_volume}
    """
    print("  Querying PM volumes (08:00-14:30 UTC = 4am-10:30am ET max window)...")
    cursor = conn.cursor()
    # 08:00 UTC = 4am EDT or 3am EST — safe lower bound for premarket
    # 14:30 UTC = 10:30am EDT or 9:30am EST — safe upper bound
    cursor.execute("""
        SELECT DATE(time) as trade_date, symbol, SUM(volume) as pm_vol
        FROM stock_candles_1m
        WHERE time >= %s AND time < %s
          AND EXTRACT(HOUR FROM time) >= 8
          AND EXTRACT(HOUR FROM time) < 15
        GROUP BY DATE(time), symbol
    """, (
        datetime(2024, 12, 1, tzinfo=UTC),
        datetime(2026, 2, 19, tzinfo=UTC)
    ))

    pm_vols = {}
    for row in cursor.fetchall():
        pm_vols[(row[0], row[1])] = int(row[2])

    print(f"  Loaded {len(pm_vols):,} (date, symbol) PM volume entries")
    return pm_vols


def load_prior_closes(conn):
    """Daily closes for all symbols. Returns {symbol: {date: close}}."""
    print("  Loading daily closes...")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DATE(time) as bar_date, symbol, close
        FROM stock_candles_1d
        WHERE time >= %s AND time < %s
        ORDER BY symbol, bar_date
    """, (datetime(2024, 12, 1, tzinfo=UTC), datetime(2026, 2, 19, tzinfo=UTC)))

    closes = defaultdict(dict)
    for row in cursor.fetchall():
        closes[row[1]][row[0]] = float(row[2]) if row[2] else None
    print(f"  Loaded closes for {len(closes):,} symbols")
    return closes


def load_fundamentals(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT symbol, float_shares, market_cap FROM stock_fundamentals")
    return {r[0]: {'float_shares': float(r[1]) if r[1] else None,
                   'market_cap':   float(r[2]) if r[2] else None}
            for r in cursor.fetchall()}


def load_day_classes():
    conn = sqlite3.connect(OPTIMIZER_DB)
    cursor = conn.cursor()
    cursor.execute('SELECT date, run_id, SUM(pnl) FROM trades GROUP BY date, run_id')
    day_data = defaultdict(list)
    for d, _, pnl in cursor.fetchall():
        day_data[d].append(pnl)
    conn.close()

    classes = {}
    for d, pnls in day_data.items():
        n   = len(pnls)
        pct = sum(1 for p in pnls if p > 0) / n if n >= 3 else -1
        if n < 3:         cls = 'DEAD'
        elif pct >= 0.60: cls = 'EASY'
        elif pct <= 0.30: cls = 'TRAP'
        elif pct >= 0.40: cls = 'SKILL'
        else:             cls = 'MIXED'
        classes[d] = cls
    return classes


def get_prior_close(closes_by_symbol, symbol, trade_date):
    sym_closes = closes_by_symbol.get(symbol, {})
    for delta in range(1, 8):
        d = trade_date - timedelta(days=delta)
        if d in sym_closes and sym_closes[d] is not None:
            return sym_closes[d]
    return None


def get_30d_avg_pm_vol(pm_vols, symbol, trade_date, trading_days_list):
    """Compute 30-day average PM volume using pre-loaded dict."""
    try:
        idx = trading_days_list.index(trade_date)
    except ValueError:
        return None
    if idx < 2:
        return None

    prior_days = trading_days_list[max(0, idx - RV_LOOKBACK):idx]
    vols = [pm_vols[(d, symbol)] for d in prior_days if (d, symbol) in pm_vols]
    vols = [v for v in vols if v > 0]
    return statistics.mean(vols) if len(vols) >= 5 else None


def process_trading_day(conn, trade_date, pm_vols, closes_by_symbol,
                        fundamentals, trading_days, day_classes):
    """
    Find all stocks that hit 10%+ from prior close during premarket on trade_date.
    Returns list of dicts with full metrics for each qualifying stock.
    """
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    date_str = trade_date.strftime('%Y-%m-%d')

    # Compute exact UTC timestamps for this day's key snapshots
    pm_start_utc  = et_to_utc(trade_date, 4,  0)   # 4:00am ET
    pm_end_utc    = et_to_utc(trade_date, 9, 30)    # 9:30am ET (full PM window)
    snap_925_lo   = et_to_utc(trade_date, 9, 20)    # window around 9:25am
    snap_925_hi   = et_to_utc(trade_date, 9, 27)
    snap_930_lo   = et_to_utc(trade_date, 9, 29)    # window around 9:30am open
    snap_930_hi   = et_to_utc(trade_date, 9, 33)
    early_pm_lo   = et_to_utc(trade_date, 4,  0)    # 4:00-4:30am
    early_pm_hi   = et_to_utc(trade_date, 4, 30)
    late_pm_lo    = et_to_utc(trade_date, 8, 55)    # 8:55-9:25am
    late_pm_hi    = et_to_utc(trade_date, 9, 25)
    trend_900_lo  = et_to_utc(trade_date, 9,  0)    # 9:00-9:05am (trend start)
    trend_900_hi  = et_to_utc(trade_date, 9,  6)

    # ── Single query: all PM stats for all symbols on this day ───────────
    cursor.execute("""
        WITH pm_bars AS (
            SELECT
                symbol,
                MAX(high)                                                      AS pm_high,
                MIN(low)                                                       AS pm_low,
                SUM(volume)                                                    AS pm_vol_total,
                SUM(CASE WHEN time >= %s AND time < %s THEN volume ELSE 0 END) AS early_pm_vol,
                SUM(CASE WHEN time >= %s AND time < %s THEN volume ELSE 0 END) AS late_pm_vol,
                COUNT(*)                                                       AS bar_count
            FROM stock_candles_1m
            WHERE time >= %s AND time < %s
            GROUP BY symbol
        ),
        first_bar AS (
            SELECT DISTINCT ON (symbol) symbol, open AS pm_open
            FROM stock_candles_1m
            WHERE time >= %s AND time < %s
            ORDER BY symbol, time
        ),
        snap_925 AS (
            SELECT DISTINCT ON (symbol) symbol, close AS close_925, rel_vol_30d
            FROM stock_candles_1m
            WHERE time >= %s AND time < %s
            ORDER BY symbol, time DESC
        ),
        snap_930 AS (
            SELECT DISTINCT ON (symbol) symbol, open AS open_930, close AS close_930
            FROM stock_candles_1m
            WHERE time >= %s AND time < %s
            ORDER BY symbol, time
        ),
        snap_900 AS (
            SELECT DISTINCT ON (symbol) symbol, close AS close_900
            FROM stock_candles_1m
            WHERE time >= %s AND time < %s
            ORDER BY symbol, time
        )
        SELECT
            pb.symbol,
            pb.pm_high, pb.pm_low, pb.pm_vol_total,
            pb.early_pm_vol, pb.late_pm_vol, pb.bar_count,
            fb.pm_open,
            s925.close_925, s925.rel_vol_30d AS rel_vol_stored,
            s930.open_930,  s930.close_930,
            s900.close_900
        FROM pm_bars pb
        LEFT JOIN first_bar fb   ON pb.symbol = fb.symbol
        LEFT JOIN snap_925  s925 ON pb.symbol = s925.symbol
        LEFT JOIN snap_930  s930 ON pb.symbol = s930.symbol
        LEFT JOIN snap_900  s900 ON pb.symbol = s900.symbol
    """, (
        early_pm_lo, early_pm_hi,   # early PM vol window
        late_pm_lo,  late_pm_hi,    # late PM vol window
        pm_start_utc, pm_end_utc,   # full PM window for pm_bars
        pm_start_utc, et_to_utc(trade_date, 5, 0),  # first bar window (4-5am)
        snap_925_lo, snap_925_hi,   # 9:25am snapshot
        snap_930_lo, snap_930_hi,   # 9:30am snapshot
        trend_900_lo, trend_900_hi, # 9:00am for trend calc
    ))

    pm_data = {r['symbol']: dict(r) for r in cursor.fetchall()}
    if not pm_data:
        return []

    results = []
    for symbol, pm in pm_data.items():

        # Prior close
        prior_close = get_prior_close(closes_by_symbol, symbol, trade_date)
        if not prior_close or prior_close <= 0:
            continue

        pm_high = float(pm['pm_high']) if pm['pm_high'] else None
        if not pm_high:
            continue

        # ── Pillar 2: hit 10%+ at any point in PM? ───────────────────────
        max_gap_pct = (pm_high - prior_close) / prior_close * 100
        if max_gap_pct < GAP_PCT_MIN:
            continue

        # ── Snapshot prices and gap% ──────────────────────────────────────
        close_925 = float(pm['close_925']) if pm['close_925'] else None
        open_930  = float(pm['open_930'])  if pm['open_930']  else None
        close_930 = float(pm['close_930']) if pm['close_930'] else None

        gap_pct_925 = ((close_925 - prior_close) / prior_close * 100) if close_925 else None
        gap_pct_930 = ((open_930  - prior_close) / prior_close * 100) if open_930  else None

        held_925 = gap_pct_925 is not None and gap_pct_925 >= GAP_PCT_MIN
        held_930 = gap_pct_930 is not None and gap_pct_930 >= GAP_PCT_MIN

        if   held_925 and held_930: qualified_when = 'HELD_BOTH'
        elif held_925:              qualified_when = 'HELD_925_ONLY'
        elif held_930:              qualified_when = 'HELD_930_ONLY'
        else:                       qualified_when = 'HIT_ONLY'

        # ── Pillar 3: relative volume ─────────────────────────────────────
        today_pm_vol = pm_vols.get((trade_date, symbol), 0)
        avg_pm_vol   = get_30d_avg_pm_vol(pm_vols, symbol, trade_date, trading_days)
        rel_vol      = (today_pm_vol / avg_pm_vol) if avg_pm_vol and avg_pm_vol > 0 else None
        pillar3_pass = rel_vol is not None and rel_vol >= REL_VOL_MIN
        rel_vol_stored = float(pm['rel_vol_stored']) if pm['rel_vol_stored'] else None

        # ── PM range ─────────────────────────────────────────────────────
        pm_low = float(pm['pm_low']) if pm['pm_low'] else None
        pm_range_pct = ((pm_high - pm_low) / prior_close * 100) if pm_low else None

        # ── PM fade by 9:25am ─────────────────────────────────────────────
        if close_925 and pm_high > prior_close:
            gain_at_high = pm_high   - prior_close
            gain_at_925  = close_925 - prior_close
            fade_pct_925 = 1.0 - (gain_at_925 / gain_at_high) if gain_at_high > 0 else 0.0
        else:
            fade_pct_925 = None

        # ── Volume acceleration ───────────────────────────────────────────
        early_vol = int(pm['early_pm_vol']) if pm['early_pm_vol'] else 0
        late_vol  = int(pm['late_pm_vol'])  if pm['late_pm_vol']  else 0
        vol_accel = (late_vol / early_vol) if early_vol > 0 else None

        # ── Late PM price trend (9:00→9:25) ──────────────────────────────
        close_900 = float(pm['close_900']) if pm['close_900'] else None
        late_pm_trend = None
        if close_900 and close_925 and close_900 > 0:
            late_pm_trend = (close_925 - close_900) / close_900 * 100

        # ── Fundamentals ─────────────────────────────────────────────────
        fund = fundamentals.get(symbol, {})
        float_shares = fund.get('float_shares')
        market_cap   = fund.get('market_cap')
        low_float    = (float_shares is not None and float_shares < 10_000_000)

        # ── Day class from optimizer ──────────────────────────────────────
        day_class = day_classes.get(date_str, 'UNKNOWN')

        results.append({
            # Identity
            'date':                date_str,
            'symbol':              symbol,
            'day_class':           day_class,

            # Pillar 2 - Gap
            'prior_close':         round(prior_close, 4),
            'pm_open':             round(float(pm['pm_open']), 4) if pm['pm_open'] else '',
            'pm_high':             round(pm_high, 4),
            'pm_low':              round(pm_low, 4)              if pm_low    else '',
            'close_925':           round(close_925, 4)           if close_925 else '',
            'open_930':            round(open_930, 4)            if open_930  else '',
            'close_930':           round(close_930, 4)           if close_930 else '',
            'max_gap_pct':         round(max_gap_pct, 2),
            'gap_pct_925':         round(gap_pct_925, 2)         if gap_pct_925 is not None else '',
            'gap_pct_930':         round(gap_pct_930, 2)         if gap_pct_930 is not None else '',
            'held_925':            held_925,
            'held_930':            held_930,
            'qualified_when':      qualified_when,

            # Pillar 3 - Relative Volume
            'pm_vol_total':        today_pm_vol,
            'avg_pm_vol_30d':      round(avg_pm_vol, 0)          if avg_pm_vol  else '',
            'rel_vol':             round(rel_vol, 2)              if rel_vol     else '',
            'rel_vol_stored':      round(rel_vol_stored, 2)       if rel_vol_stored else '',
            'pillar3_pass':        pillar3_pass,

            # PM detail metrics
            'pm_range_pct':        round(pm_range_pct, 2)        if pm_range_pct   else '',
            'fade_pct_925':        round(fade_pct_925, 3)        if fade_pct_925 is not None else '',
            'early_pm_vol':        early_vol,
            'late_pm_vol':         late_vol,
            'vol_acceleration':    round(vol_accel, 2)           if vol_accel   else '',
            'late_pm_trend_pct':   round(late_pm_trend, 2)       if late_pm_trend is not None else '',
            'bar_count':           int(pm['bar_count'])           if pm['bar_count'] else 0,

            # Fundamentals
            'float_shares':        int(float_shares)              if float_shares else '',
            'market_cap':          int(market_cap)                if market_cap   else '',
            'low_float':           low_float,
        })

    return results


def main():
    print("=" * 70)
    print("  BUILD DAILY GAPPER UNIVERSE")
    print("  Pillars 2 (10%+ gap) + 3 (5x+ relative volume)")
    print("=" * 70)

    conn = psycopg2.connect(TSDB_CONN, connect_timeout=10)

    print("\n[1/5] Loading trading days...", flush=True)
    trading_days = get_trading_days(conn)
    print(f"  Found {len(trading_days)} trading days ({trading_days[0]} to {trading_days[-1]})")

    print("\n[2/5] Loading all PM volumes...", flush=True)
    pm_vols = load_all_pm_volumes(conn)

    print("\n[3/5] Loading daily closes...", flush=True)
    closes_by_symbol = load_prior_closes(conn)

    print("\n[4/5] Loading fundamentals + day classes...", flush=True)
    fundamentals = load_fundamentals(conn)
    day_classes  = load_day_classes()
    print(f"  Fundamentals: {len(fundamentals):,} symbols  |  Day classes: {len(day_classes)} dates")

    print(f"\n[5/5] Processing {len(trading_days)} trading days...", flush=True)
    import time as _time
    all_rows = []
    t0 = _time.time()
    for i, trade_date in enumerate(trading_days):
        rows = process_trading_day(
            conn, trade_date, pm_vols, closes_by_symbol,
            fundamentals, trading_days, day_classes
        )
        all_rows.extend(rows)
        if (i + 1) % 25 == 0 or i == 0:
            elapsed = _time.time() - t0
            rate    = (i + 1) / elapsed
            eta     = (len(trading_days) - i - 1) / rate
            print(f"  [{i+1:>3}/{len(trading_days)}] {trade_date}  "
                  f"rows={len(all_rows):,}  "
                  f"elapsed={elapsed:.0f}s  eta={eta:.0f}s", flush=True)

    conn.close()

    if not all_rows:
        print("\nNo qualifying rows — check thresholds.")
        return

    # Write CSV
    fieldnames = list(all_rows[0].keys())
    with open(OUTPUT_CSV, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    # ── Summary ──────────────────────────────────────────────────────────
    p2_and_3 = [r for r in all_rows if r['pillar3_pass']]
    qw_counts = Counter(r['qualified_when'] for r in all_rows)
    dc_counts_all = Counter(r['day_class'] for r in p2_and_3)

    print(f"\n{'=' * 70}")
    print(f"  RESULTS SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total rows (passed pillar 2 = hit 10%+):    {len(all_rows):>7,}")
    print(f"  Also passed pillar 3 (5x+ rel vol):         {len(p2_and_3):>7,}")
    print(f"\n  Qualification timing (for all pillar-2 stocks):")
    for qw in ['HELD_BOTH', 'HELD_925_ONLY', 'HELD_930_ONLY', 'HIT_ONLY']:
        print(f"    {qw:<20} {qw_counts.get(qw, 0):>6,}")
    print(f"\n  Pillars 2+3 stocks by day class:")
    for cls in ['EASY', 'TRAP', 'SKILL', 'MIXED', 'UNKNOWN']:
        n = dc_counts_all.get(cls, 0)
        if n:
            days = len(set(r['date'] for r in p2_and_3 if r['day_class'] == cls))
            avg  = n / days if days else 0
            print(f"    {cls:<10} {n:>5,} stocks across {days:>3} days  ({avg:.1f}/day avg)")
    print(f"\n  Output: {OUTPUT_CSV}")


if __name__ == '__main__':
    main()
