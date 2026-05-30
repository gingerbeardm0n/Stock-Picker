"""
Market Temperature Validation Script
=====================================
For every trading day in the date range:

  1. PREDICT  — classify market temperature using 4am–9:25am premarket bars
                (same logic as classify_premarket() in production)

  2. ACTUAL   — measure what the market actually did 9:30–10:30am
                Three metrics, combined into a momentum score, then quantile-
                ranked to assign HOT/NEUTRAL/COLD matching corpus distribution
                (HOT=46%, NEUTRAL=22%, COLD=32%)

  3. COMPARE  — build confusion matrix, compute accuracy per class

  4. OUTPUT
       research/analysis/outputs/market_temp_validation.csv  — one row/day
       research/analysis/outputs/hot_days.csv                — for Optuna
       research/analysis/outputs/neutral_days.csv
       research/analysis/outputs/cold_days.csv

Ground truth methodology:
  Metric 1 (weight 50%): max_run_pct
      For each qualifying symbol: (HOD 9:30–10:30) / (open at 9:30) - 1
      Best run across all symbols on the day.

  Metric 2 (weight 30%): breadth_count
      # of symbols whose HOD 9:30–10:30 >= prior_close * 1.15 (up 15%+)

  Metric 3 (weight 20%): avg_window_vol_ratio
      Average of (total volume in 9:30–10:30 window / prior day total volume)
      across all qualifying symbols.  Captures whether today's open is busier
      than a normal day for these stocks — no pre-computed column required.

  All three normalized to [0,1] then combined into momentum_score.
  Quantile cutoffs: top 46% = HOT, next 22% = NEUTRAL, bottom 32% = COLD.

Premarket features (for classifier):
  premarket_qualifying_count  — # symbols up 10%+ from prior close at 9:25am
  premarket_gapper_pct        — leading (max) gap%
  premarket_avg_top5_gap      — average gap% of top 5 qualifying symbols
  premarket_total_dv          — sum(price × volume) across qualifying symbols, 4am–9:15am
  premarket_vol_accel         — total volume 8:45–9:15am / total volume 4:00–4:30am
                                 (build-up signal: is premarket getting busier near open?)

Usage:
    python research/analysis/scripts/validate_market_temperature.py
    python research/analysis/scripts/validate_market_temperature.py --year 2022
    python research/analysis/scripts/validate_market_temperature.py --start 2021-01-01 --end 2024-12-31

    # Tune classification thresholds:
    python research/analysis/scripts/validate_market_temperature.py --hot-gap 30 --warm-gap 15 --hot-syms 3
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import psycopg2
import pytz

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../production')))

ET = pytz.timezone('US/Eastern')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)

DB_CONN = 'postgresql://postgres:changeme123@localhost:5432/stockdata'

# ── Scanner filter (5-pillar defaults) ───────────────────────────────────────
MIN_PRICE   = 1.0
MAX_PRICE   = 20.0
MIN_GAP_PCT = 10.0   # % gain vs prior close → "qualifying symbol"

# ── Corpus distribution targets ───────────────────────────────────────────────
HOT_PCT     = 0.46
NEUTRAL_PCT = 0.22
COLD_PCT    = 0.32


# ── Database helpers ──────────────────────────────────────────────────────────

def get_trading_days(conn, start: date, end: date) -> list[date]:
    """All dates that have entries in tradable_stocks_by_date — fast, no full scan."""
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT date FROM tradable_stocks_by_date "
        "WHERE date >= %s AND date <= %s ORDER BY date",
        (start.isoformat(), end.isoformat()),
    )
    days = [r[0] for r in cur.fetchall()]
    logger.info(f"Trading days in range: {len(days)}  ({start} to {end})")
    return days


def get_prior_close_bulk(
    conn,
    trading_days: list[date],
) -> tuple[dict[date, dict[str, float]], dict[date, dict[str, float]]]:
    """
    Load prior close prices AND prior day volumes for all days at once.

    Returns:
        prior_close_by_day  — {trading_day: {symbol: close_price}}
        prior_volume_by_day — {trading_day: {symbol: total_daily_volume}}

    Uses the daily bar from the previous calendar day (closest prior day in DB).
    """
    if not trading_days:
        return {}, {}

    range_start = trading_days[0] - timedelta(days=7)
    range_end   = trading_days[-1]

    logger.info(f"Loading daily bars for prior-close lookup ({range_start} to {range_end})...")
    cur = conn.cursor()
    cur.execute("""
        SELECT DATE(time AT TIME ZONE 'America/New_York') as dt, symbol, close, volume
        FROM stock_candles_1d
        WHERE time >= %s AND time < %s
          AND close BETWEEN %s AND %s
        ORDER BY dt, symbol
    """, (range_start.isoformat(), (range_end + timedelta(days=1)).isoformat(),
          MIN_PRICE * 0.3, MAX_PRICE * 5))

    daily_close:  dict[date, dict[str, float]] = defaultdict(dict)
    daily_volume: dict[date, dict[str, float]] = defaultdict(dict)
    for dt, sym, close, vol in cur.fetchall():
        daily_close[dt][sym]  = float(close)
        daily_volume[dt][sym] = float(vol) if vol else 0.0

    all_daily_dates = sorted(daily_close.keys())
    prior_close_by_day:  dict[date, dict[str, float]] = {}
    prior_volume_by_day: dict[date, dict[str, float]] = {}

    for tday in trading_days:
        prior_dates = [d for d in all_daily_dates if d < tday]
        if not prior_dates:
            continue
        prev = prior_dates[-1]
        prior_close_by_day[tday]  = daily_close[prev]
        prior_volume_by_day[tday] = daily_volume[prev]

    logger.info(f"  Prior close loaded for {len(prior_close_by_day)} of {len(trading_days)} days")
    return prior_close_by_day, prior_volume_by_day


def get_bars_for_day(conn, trading_day: date, hour_start: int, minute_start: int,
                     hour_end: int, minute_end: int) -> list[dict]:
    """
    Load all 1-min bars for a single trading day within an ET time window.
    Returns list of bar dicts: time (UTC-aware datetime), symbol, open, high, close, volume.
    """
    local_start = ET.localize(datetime(trading_day.year, trading_day.month, trading_day.day,
                                        hour_start, minute_start, 0))
    local_end   = ET.localize(datetime(trading_day.year, trading_day.month, trading_day.day,
                                        hour_end, minute_end, 0))

    cur = conn.cursor()
    cur.execute("""
        SELECT time, symbol, open, high, close, volume
        FROM stock_candles_1m
        WHERE time >= %s AND time < %s
          AND close BETWEEN %s AND %s
        ORDER BY symbol, time
    """, (local_start.isoformat(), local_end.isoformat(),
          MIN_PRICE * 0.3, MAX_PRICE * 5))

    return [
        {
            'time':   r[0],          # timezone-aware UTC datetime from psycopg2
            'symbol': r[1],
            'open':   float(r[2]),
            'high':   float(r[3]),
            'close':  float(r[4]),
            'volume': int(r[5]),
        }
        for r in cur.fetchall()
    ]


# ── Premarket classification ──────────────────────────────────────────────────

def classify_premarket(
    premarket_bars: list[dict],
    prior_close: dict[str, float],
    hot_gap: float,
    warm_gap: float,
    hot_syms: int,
    cold_syms: int,
) -> dict:
    """
    Classify market temperature from 4am–9:25am bars.

    Replicates production/trading/market_temperature.py::classify_premarket()
    and computes five premarket features:
      - premarket_qualifying_count  (existing)
      - premarket_gapper_pct        (existing — leading gapper, max)
      - premarket_avg_top5_gap      (NEW — average of top 5 gap%)
      - premarket_total_dv          (NEW — total dollar volume of qualifying syms)
      - premarket_vol_accel         (NEW — late premarket vol / early premarket vol)
    """
    # Group bars by symbol (bars are ordered symbol, time)
    sym_bars: dict[str, list[dict]] = defaultdict(list)
    for bar in premarket_bars:
        sym_bars[bar['symbol']].append(bar)

    # Determine qualifying symbols and their gap%
    gap_by_sym: dict[str, float] = {}
    leading_gapper_pct = 0.0
    leading_gapper_sym = None

    for sym, bars in sym_bars.items():
        last_price = bars[-1]['close']   # last premarket bar close ≈ 9:25am price
        if not (MIN_PRICE <= last_price <= MAX_PRICE):
            continue
        pc = prior_close.get(sym)
        if not pc or pc <= 0:
            continue
        gap_pct = (last_price - pc) / pc * 100.0
        if gap_pct >= MIN_GAP_PCT:
            gap_by_sym[sym] = gap_pct
            if gap_pct > leading_gapper_pct:
                leading_gapper_pct = gap_pct
                leading_gapper_sym = sym

    qualifying_syms = list(gap_by_sym.keys())
    syms_count      = len(qualifying_syms)

    # ── Feature: avg_top5_gap — less sensitive to single outlier gapper ───────
    top5_gaps     = sorted(gap_by_sym.values(), reverse=True)[:5]
    avg_top5_gap  = round(sum(top5_gaps) / len(top5_gaps), 2) if top5_gaps else 0.0

    # ── Features: total_dv + vol_accel — iterate qualifying symbol bars once ──
    total_dv  = 0.0
    early_vol = 0    # 4:00–4:30 ET (first 30 min of premarket)
    late_vol  = 0    # 8:45–9:15 ET (final 30 min before open)

    for sym in qualifying_syms:
        for bar in sym_bars[sym]:
            total_dv += bar['close'] * bar['volume']

            # Classify bar into early vs late window via ET time
            try:
                bar_et = bar['time'].astimezone(ET)
                h, m   = bar_et.hour, bar_et.minute
                if h == 4 and m < 30:
                    early_vol += bar['volume']
                elif (h == 8 and m >= 45) or (h == 9 and m < 15):
                    late_vol += bar['volume']
            except Exception:
                pass   # naive or malformed timestamp — skip vol_accel for this bar

    # Require meaningful early volume to avoid divide-by-near-zero noise
    vol_accel = round(late_vol / early_vol, 3) if early_vol > 5_000 else 1.0

    # ── Classification (unchanged production logic) ────────────────────────────
    if leading_gapper_pct >= hot_gap and syms_count >= hot_syms:
        label = 'HOT'
    elif leading_gapper_pct >= warm_gap or syms_count > cold_syms:
        label = 'NEUTRAL'
    else:
        label = 'COLD'

    return {
        'predicted_label':            label,
        'premarket_gapper_pct':       round(leading_gapper_pct, 2),
        'premarket_gapper_sym':       leading_gapper_sym or '',
        'premarket_qualifying_count': syms_count,
        'premarket_avg_top5_gap':     avg_top5_gap,
        'premarket_total_dv':         int(total_dv),
        'premarket_vol_accel':        vol_accel,
    }


# ── SPY premarket data ────────────────────────────────────────────────────────

SPY_CSV = os.path.abspath(os.path.join(os.path.dirname(__file__), '../outputs/spy_premarket_history.csv'))

def load_spy_data(csv_path: str = SPY_CSV) -> dict[str, dict]:
    """
    Load spy_premarket_history.csv, compute 3 derived features per day:
      spy_gap_pct       = (market_open - prior_close) / prior_close * 100
      spy_pm_trend_pct  = (pm_close - pm_open) / pm_open * 100
      spy_pm_vol_ratio  = pm_volume / prev_day_pm_volume  (rolling day-over-day)

    Returns dict keyed by ISO date string. Returns {} if file not found.
    """
    if not os.path.exists(csv_path):
        logger.warning(f"SPY CSV not found: {csv_path} -- SPY features will be 0")
        return {}

    rows = []
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'date':        row['date'],
                'prior_close': float(row['prior_close']),
                'pm_open':     float(row['pm_open']),
                'pm_close':    float(row['pm_close']),
                'pm_volume':   int(row['pm_volume']),
                'market_open': float(row['market_open']) if row.get('market_open') else None,
            })
    rows.sort(key=lambda r: r['date'])

    spy_by_date: dict[str, dict] = {}
    prev_pm_vol = None

    for row in rows:
        pc  = row['prior_close']
        mo  = row['market_open']
        po  = row['pm_open']
        pmc = row['pm_close']
        pv  = row['pm_volume']

        spy_gap_pct      = round((mo - pc) / pc * 100, 3)  if (mo and pc > 0)           else 0.0
        spy_pm_trend_pct = round((pmc - po) / po * 100, 3) if po > 0                    else 0.0
        spy_pm_vol_ratio = round(pv / prev_pm_vol, 3)      if (prev_pm_vol and prev_pm_vol > 0) else 1.0

        spy_by_date[row['date']] = {
            'spy_gap_pct':      spy_gap_pct,
            'spy_pm_trend_pct': spy_pm_trend_pct,
            'spy_pm_vol_ratio': spy_pm_vol_ratio,
        }
        prev_pm_vol = pv

    logger.info(f"SPY data loaded: {len(spy_by_date)} days")
    return spy_by_date


_SPY_ZERO = {'spy_gap_pct': 0.0, 'spy_pm_trend_pct': 0.0, 'spy_pm_vol_ratio': 1.0}


# ── Ground truth computation ──────────────────────────────────────────────────

def compute_ground_truth_metrics(
    trading_bars: list[dict],
    prior_close:  dict[str, float],
    prior_volume: dict[str, float],
) -> dict:
    """
    Compute three raw ground truth metrics from 9:30–10:30am bars.
    Labels are NOT assigned here — done later via quantile ranking.

    Metric 3 fix: avg_window_vol_ratio = mean(window_vol / prior_day_vol)
    per qualifying symbol.  Replaces broken rel_vol_30d column (was always 1.0).
    """
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for bar in trading_bars:
        by_symbol[bar['symbol']].append(bar)

    max_run_pct   = 0.0
    max_run_sym   = None
    breadth_count = 0
    vol_ratios:   list[float] = []

    for sym, bars in by_symbol.items():
        if not bars:
            continue
        pc = prior_close.get(sym)
        if not pc or pc <= 0:
            continue

        open_930 = bars[0]['open']
        if open_930 <= 0:
            continue

        max_high = max(b['high'] for b in bars)

        # Metric 1: run from 9:30 open to HOD
        run = (max_high - open_930) / open_930 * 100.0
        if run > max_run_pct:
            max_run_pct = run
            max_run_sym = sym

        # Metric 2: breadth — symbol reached 15%+ above prior close during window
        if max_high >= pc * 1.15:
            breadth_count += 1

        # Metric 3: volume in this window vs prior day total volume
        pv = prior_volume.get(sym)
        if pv and pv > 0:
            window_vol = sum(b['volume'] for b in bars)
            vol_ratios.append(window_vol / pv)

    avg_vol_ratio = round(sum(vol_ratios) / len(vol_ratios), 4) if vol_ratios else 0.0

    return {
        'actual_max_run_pct':      round(max_run_pct, 2),
        'actual_max_run_sym':      max_run_sym or '',
        'actual_breadth_count':    breadth_count,
        'actual_avg_vol_ratio':    avg_vol_ratio,
    }


# ── Quantile labeling ─────────────────────────────────────────────────────────

def assign_quantile_labels(results: list[dict]) -> list[dict]:
    """
    Assign actual_label to each day via quantile ranking of momentum_score.
    Corpus targets: HOT=46%, NEUTRAL=22%, COLD=32%.

    momentum_score = 0.50 * norm(max_run) + 0.30 * norm(breadth) + 0.20 * norm(vol_ratio)
    All metrics normalized to [0,1] across all days before combining.
    """
    n = len(results)
    if n == 0:
        return results

    def normalize(vals: list[float]) -> list[float]:
        mn, mx = min(vals), max(vals)
        if mx <= mn:
            return [0.5] * len(vals)
        return [(v - mn) / (mx - mn) for v in vals]

    runs   = [r['actual_max_run_pct']   for r in results]
    breds  = [float(r['actual_breadth_count']) for r in results]
    vols   = [r['actual_avg_vol_ratio'] for r in results]

    norm_runs  = normalize(runs)
    norm_breds = normalize(breds)
    norm_vols  = normalize(vols)

    scores = [
        0.50 * norm_runs[i] + 0.30 * norm_breds[i] + 0.20 * norm_vols[i]
        for i in range(n)
    ]

    # Rank highest → lowest; assign labels by quantile
    ranked_indices = sorted(range(n), key=lambda i: scores[i], reverse=True)
    hot_n     = round(n * HOT_PCT)
    neutral_n = round(n * NEUTRAL_PCT)

    labels = ['COLD'] * n
    for rank, idx in enumerate(ranked_indices):
        if rank < hot_n:
            labels[idx] = 'HOT'
        elif rank < hot_n + neutral_n:
            labels[idx] = 'NEUTRAL'
        # else COLD (already set)

    for i, r in enumerate(results):
        r['actual_label']   = labels[i]
        r['momentum_score'] = round(scores[i], 4)
        r['correct']        = (r['predicted_label'] == r['actual_label'])

    return results


# ── Reporting ─────────────────────────────────────────────────────────────────

def print_confusion_matrix(results: list[dict]) -> None:
    classes = ['HOT', 'NEUTRAL', 'COLD']
    matrix  = {p: {a: 0 for a in classes} for p in classes}

    for r in results:
        p = r.get('predicted_label', '')
        a = r.get('actual_label', '')
        if p in matrix and a in classes:
            matrix[p][a] += 1

    total   = len(results)
    correct = sum(1 for r in results if r.get('correct'))

    print()
    print('=' * 62)
    print(f'  MARKET TEMPERATURE VALIDATION  ({total} trading days)')
    print('=' * 62)
    print()
    print('  Confusion Matrix:')
    print(f'  {"":12}        ACTUAL HOT    NEUTRAL      COLD')
    for p in classes:
        row = '  '.join(f'{matrix[p][a]:>8}' for a in classes)
        print(f'  PRED {p:<7}     {row}')
    print()
    print(f'  Overall accuracy : {correct / total * 100:.1f}%   ({correct}/{total} correct)')
    print()

    for cls in classes:
        tp = matrix[cls][cls]
        fp = sum(matrix[p][cls] for p in classes if p != cls)
        fn = sum(matrix[cls][a] for a in classes if a != cls)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0
        n_actual = tp + fn
        print(f'  {cls:<7}  prec={prec:.0%}  rec={rec:.0%}  f1={f1:.0%}  (n_actual={n_actual})')

    print()
    print('  Distribution check:')
    for cls in classes:
        n_pred   = sum(1 for r in results if r.get('predicted_label') == cls)
        n_actual = sum(1 for r in results if r.get('actual_label')    == cls)
        print(f'  {cls:<7}  predicted={n_pred:>4} ({n_pred/total:.0%})   '
              f'actual={n_actual:>4} ({n_actual/total:.0%})')
    print()
    print('  Feature correlations with actual_label (0=COLD,1=NEUTRAL,2=HOT):')
    label_num = {'COLD': 0, 'NEUTRAL': 1, 'HOT': 2}
    actuals = [label_num[r['actual_label']] for r in results]
    features = [
        'premarket_qualifying_count',
        'premarket_gapper_pct',
        'premarket_avg_top5_gap',
        'premarket_total_dv',
        'premarket_vol_accel',
        'spy_gap_pct',
        'spy_pm_trend_pct',
        'spy_pm_vol_ratio',
    ]
    import math
    for feat in features:
        vals = [r.get(feat, 0) for r in results]
        # Pearson r
        n = len(vals)
        mx = sum(vals) / n; my = sum(actuals) / n
        num = sum((vals[i] - mx) * (actuals[i] - my) for i in range(n))
        dx  = math.sqrt(sum((v - mx)**2 for v in vals))
        dy  = math.sqrt(sum((a - my)**2 for a in actuals))
        r   = num / (dx * dy) if dx * dy > 0 else 0.0
        print(f'    {feat:<35}: r={r:+.3f}')
    print()
    print('=' * 62)
    print()


def save_outputs(results: list[dict], output_dir: str) -> None:
    os.makedirs(output_dir, exist_ok=True)

    # ── Main validation CSV ───────────────────────────────────────────────────
    main_path = os.path.join(output_dir, 'market_temp_validation.csv')
    fieldnames = [
        'date', 'predicted_label', 'actual_label', 'correct', 'momentum_score',
        # Premarket features (classifier input)
        'premarket_qualifying_count',
        'premarket_gapper_pct',
        'premarket_gapper_sym',
        'premarket_avg_top5_gap',
        'premarket_total_dv',
        'premarket_vol_accel',
        # SPY index features
        'spy_gap_pct',
        'spy_pm_trend_pct',
        'spy_pm_vol_ratio',
        # Ground truth metrics
        'actual_max_run_pct',
        'actual_max_run_sym',
        'actual_breadth_count',
        'actual_avg_vol_ratio',
    ]
    with open(main_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(sorted(results, key=lambda r: r['date']))
    logger.info(f"Saved validation results: {main_path}")

    # ── Per-label date-bucket CSVs (for Optuna --symbols-file input) ──────────
    for label in ('HOT', 'NEUTRAL', 'COLD'):
        bucket = sorted([r for r in results if r['actual_label'] == label],
                        key=lambda r: r['date'])
        path = os.path.join(output_dir, f'{label.lower()}_days.csv')
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'momentum_score', 'predicted_label'])
            for r in bucket:
                writer.writerow([r['date'], r.get('momentum_score', ''), r.get('predicted_label', '')])
        logger.info(f"  {label:<7} {len(bucket):>4} days  ->  {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Validate market temperature premarket classification accuracy',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--start',      default='2021-01-01', help='Start date YYYY-MM-DD')
    parser.add_argument('--end',        default='2024-12-31', help='End date   YYYY-MM-DD')
    parser.add_argument('--year',       type=int,             help='Run single year (overrides --start/--end)')
    parser.add_argument('--output-dir', default='research/analysis/outputs')

    # Tunable classification thresholds (default = MarketTemperatureConfig defaults)
    parser.add_argument('--hot-gap',   type=float, default=50.0,
                        help='Leading gapper %% threshold for HOT (default 50.0)')
    parser.add_argument('--warm-gap',  type=float, default=20.0,
                        help='Leading gapper %% threshold for NEUTRAL (default 20.0)')
    parser.add_argument('--hot-syms',  type=int,   default=3,
                        help='Min qualifying symbols for HOT (default 3)')
    parser.add_argument('--cold-syms', type=int,   default=2,
                        help='Max qualifying symbols for COLD (default 2)')

    args = parser.parse_args()

    if args.year:
        start = date(args.year, 1, 1)
        end   = date(args.year, 12, 31)
    else:
        start = date.fromisoformat(args.start)
        end   = date.fromisoformat(args.end)

    logger.info(f"Range     : {start} to {end}")
    logger.info(f"HOT gate  : gapper >= {args.hot_gap}%  AND  symbols >= {args.hot_syms}")
    logger.info(f"NEUTRAL   : gapper >= {args.warm_gap}%  OR   symbols >  {args.cold_syms}")
    logger.info(f"COLD      : everything else")

    conn = psycopg2.connect(DB_CONN)

    # ── Load all trading days in range ────────────────────────────────────────
    trading_days = get_trading_days(conn, start, end)
    if len(trading_days) < 2:
        logger.error("Need at least 2 trading days (first day skipped for prior-close)")
        conn.close()
        return

    # ── Load SPY premarket features (from CSV) ────────────────────────────────
    spy_data = load_spy_data()

    # ── Bulk-load prior close prices + volumes (single query) ─────────────────
    prior_close_by_day, prior_volume_by_day = get_prior_close_bulk(conn, trading_days)

    # ── Process each day ──────────────────────────────────────────────────────
    results: list[dict] = []
    skipped = 0

    for i, day in enumerate(trading_days):
        if i == 0:
            continue   # skip first day (no prior close)

        prior_close  = prior_close_by_day.get(day)
        prior_volume = prior_volume_by_day.get(day, {})
        if not prior_close:
            skipped += 1
            continue

        # Load bars for both windows
        premarket_bars = get_bars_for_day(conn, day,  4,  0,  9, 25)
        trading_bars   = get_bars_for_day(conn, day,  9, 30, 10, 30)

        if not premarket_bars:
            skipped += 1
            continue
        if not trading_bars:
            skipped += 1
            continue

        # Classify premarket (5 features)
        pm = classify_premarket(
            premarket_bars, prior_close,
            args.hot_gap, args.warm_gap,
            args.hot_syms, args.cold_syms,
        )

        # Compute ground truth metrics (fixed vol ratio)
        gt = compute_ground_truth_metrics(trading_bars, prior_close, prior_volume)

        row = {'date': day.isoformat()}
        row.update(pm)
        row.update(gt)
        row.update(spy_data.get(day.isoformat(), _SPY_ZERO))
        results.append(row)

        if (i % 100) == 0 and i > 0:
            done  = i + 1
            total = len(trading_days)
            pct   = done / total * 100
            logger.info(f"  {done}/{total} ({pct:.0f}%)  last={day}  results={len(results)}")

    conn.close()

    if not results:
        logger.error("No results — check date range and DB coverage")
        return

    logger.info(f"Processed {len(results)} days  (skipped {skipped})")
    logger.info("Assigning quantile labels...")

    # ── Quantile label assignment ─────────────────────────────────────────────
    results = assign_quantile_labels(results)

    # ── Report + save ─────────────────────────────────────────────────────────
    print_confusion_matrix(results)
    save_outputs(results, args.output_dir)

    logger.info("Done.")


if __name__ == '__main__':
    main()
