#!/usr/bin/env python3
"""
Regime-Specific Winner Analysis
================================
Analyzes optimizer trial results to find trials that excelled in specific months,
even if they failed overall. Goal: understand the "ceiling" of a perfect regime detector.

Database: optimizer/robust_results.db
- runs table: id, run_id, total_trades, winners, losers, win_rate, profit_factor, total_pnl, ...
- trades table: id, run_id, date, symbol, pattern, entry_price, exit_price, shares, pnl, ...
"""

import sqlite3
import json
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent / "robust_results.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def extract_trial_number(run_id: str) -> int:
    """Extract trial number from run_id like 'optuna_00198'."""
    return int(run_id.split("_")[1])


def section(title: str):
    """Print a section header."""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


# =============================================================================
# PART 1: Monthly P&L breakdown for ALL trials
# =============================================================================
def get_monthly_pnl_all_trials(conn):
    """
    Returns dict: {run_id: {month_str: pnl_sum}}
    Also returns {run_id: total_pnl} for reference.
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id,
               strftime('%Y-%m', date) as month,
               SUM(pnl) as month_pnl,
               COUNT(*) as trade_count,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners,
               SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) as losers
        FROM trades
        GROUP BY run_id, strftime('%Y-%m', date)
        ORDER BY run_id, month
    """)

    monthly = defaultdict(dict)  # {run_id: {month: pnl}}
    monthly_detail = defaultdict(dict)  # {run_id: {month: {pnl, trades, winners, losers}}}

    for row in cur.fetchall():
        run_id = row["run_id"]
        month = row["month"]
        monthly[run_id][month] = row["month_pnl"]
        monthly_detail[run_id][month] = {
            "pnl": row["month_pnl"],
            "trades": row["trade_count"],
            "winners": row["winners"],
            "losers": row["losers"],
        }

    # Get total P&L from runs table
    cur.execute("SELECT run_id, total_pnl, total_trades FROM runs ORDER BY total_pnl DESC")
    totals = {row["run_id"]: {"total_pnl": row["total_pnl"], "total_trades": row["total_trades"]} for row in cur.fetchall()}

    return monthly, monthly_detail, totals


# =============================================================================
# PART 2: Best trial per month
# =============================================================================
def find_best_per_month(monthly):
    """For each month, find which trial had the highest P&L."""
    all_months = sorted(set(m for months in monthly.values() for m in months))

    best_per_month = {}
    for month in all_months:
        best_run = None
        best_pnl = float("-inf")
        for run_id, months_data in monthly.items():
            pnl = months_data.get(month, 0)
            if pnl > best_pnl:
                best_pnl = pnl
                best_run = run_id
        best_per_month[month] = {"run_id": best_run, "pnl": best_pnl}

    return best_per_month, all_months


# =============================================================================
# PART 3: Monthly pattern/config analysis for top trials
# =============================================================================
def get_monthly_patterns(conn, run_id, month):
    """Get pattern breakdown for a specific trial in a specific month."""
    cur = conn.cursor()
    cur.execute("""
        SELECT pattern, COUNT(*) as cnt, SUM(pnl) as total_pnl,
               AVG(pnl) as avg_pnl,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins
        FROM trades
        WHERE run_id = ? AND strftime('%Y-%m', date) = ?
        GROUP BY pattern
        ORDER BY total_pnl DESC
    """, (run_id, month))
    return cur.fetchall()


def get_trial_params(conn, run_id):
    """Get params_json for a trial."""
    cur = conn.cursor()
    cur.execute("SELECT params_json FROM runs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    if row:
        return json.loads(row["params_json"])
    return {}


def get_monthly_exit_reasons(conn, run_id, month):
    """Get exit reason breakdown for a trial in a month."""
    cur = conn.cursor()
    cur.execute("""
        SELECT exit_reason, COUNT(*) as cnt, SUM(pnl) as total_pnl
        FROM trades
        WHERE run_id = ? AND strftime('%Y-%m', date) = ?
        GROUP BY exit_reason
        ORDER BY cnt DESC
    """, (run_id, month))
    return cur.fetchall()


# =============================================================================
# PART 4: Top-N per month (for cluster analysis)
# =============================================================================
def find_top_n_per_month(monthly, n=5):
    """For each month, find the top N trials."""
    all_months = sorted(set(m for months in monthly.values() for m in months))

    top_n = {}
    for month in all_months:
        # Collect all trials' PnL for this month
        month_results = []
        for run_id, months_data in monthly.items():
            pnl = months_data.get(month, 0)
            month_results.append((run_id, pnl))
        month_results.sort(key=lambda x: x[1], reverse=True)
        top_n[month] = month_results[:n]

    return top_n


# =============================================================================
# PART 5: Trial 198 baseline
# =============================================================================
def get_trial_198_monthly(monthly):
    """Get trial 198's monthly breakdown for comparison."""
    run_id_198 = "optuna_00198"
    if run_id_198 in monthly:
        return monthly[run_id_198]
    # Try to find it
    for run_id in monthly:
        if "198" in run_id:
            return monthly[run_id]
    return {}


# =============================================================================
# MAIN ANALYSIS
# =============================================================================
def main():
    conn = get_connection()

    # ---- Load data ----
    monthly, monthly_detail, totals = get_monthly_pnl_all_trials(conn)
    best_per_month, all_months = find_best_per_month(monthly)
    top5_per_month = find_top_n_per_month(monthly, n=5)

    num_trials = len(monthly)

    # =========================================================================
    section("1. OVERVIEW")
    # =========================================================================
    print(f"Total trials with trades: {num_trials}")
    print(f"Date range: {all_months[0]} to {all_months[-1]} ({len(all_months)} months)")
    print(f"Total trades in database: {sum(t['total_trades'] for t in totals.values())}")

    # Top 10 overall
    sorted_totals = sorted(totals.items(), key=lambda x: x[1]["total_pnl"], reverse=True)
    print(f"\nTop 10 trials overall:")
    print(f"  {'Trial':>8}  {'Total P&L':>10}  {'Trades':>7}")
    print(f"  {'-'*8}  {'-'*10}  {'-'*7}")
    for run_id, data in sorted_totals[:10]:
        trial = extract_trial_number(run_id)
        print(f"  #{trial:>6}  ${data['total_pnl']:>9.2f}  {data['total_trades']:>7}")

    # =========================================================================
    section("2. BEST TRIAL PER MONTH (Perfect Regime Detector Ceiling)")
    # =========================================================================

    composite_pnl = 0
    trial_198_total = 0
    t198_monthly = get_trial_198_monthly(monthly)

    print(f"  {'Month':>8}  {'Best Trial':>11}  {'Best P&L':>10}  {'T198 P&L':>10}  {'Delta':>10}")
    print(f"  {'-'*8}  {'-'*11}  {'-'*10}  {'-'*10}  {'-'*10}")

    for month in all_months:
        best = best_per_month[month]
        trial_num = extract_trial_number(best["run_id"])
        best_pnl = best["pnl"]
        t198_pnl = t198_monthly.get(month, 0)
        delta = best_pnl - t198_pnl
        composite_pnl += best_pnl
        trial_198_total += t198_pnl

        print(f"  {month:>8}  #{trial_num:>9}  ${best_pnl:>9.2f}  ${t198_pnl:>9.2f}  ${delta:>+9.2f}")

    print(f"  {'-'*8}  {'-'*11}  {'-'*10}  {'-'*10}  {'-'*10}")
    print(f"  {'TOTAL':>8}  {'COMPOSITE':>11}  ${composite_pnl:>9.2f}  ${trial_198_total:>9.2f}  ${composite_pnl - trial_198_total:>+9.2f}")

    print(f"\n  Composite Dynamic P&L: ${composite_pnl:,.2f}")
    print(f"  Trial 198 Flat P&L:    ${trial_198_total:,.2f}")
    print(f"  Improvement:           ${composite_pnl - trial_198_total:,.2f} ({((composite_pnl / trial_198_total - 1) * 100) if trial_198_total != 0 else 0:.1f}%)")

    # =========================================================================
    section("3. MONTH WINNER CLUSTERS: Do the same trials keep winning?")
    # =========================================================================

    # Count how many months each trial wins
    winner_counts = defaultdict(list)
    for month in all_months:
        winner = best_per_month[month]["run_id"]
        winner_counts[winner].append(month)

    print(f"  Unique monthly winners: {len(winner_counts)} (out of {len(all_months)} months)\n")

    # Sort by number of months won
    sorted_winners = sorted(winner_counts.items(), key=lambda x: len(x[1]), reverse=True)
    print(f"  {'Trial':>8}  {'Months Won':>11}  {'Months'}")
    print(f"  {'-'*8}  {'-'*11}  {'-'*40}")
    for run_id, months_won in sorted_winners:
        trial = extract_trial_number(run_id)
        print(f"  #{trial:>6}  {len(months_won):>11}  {', '.join(months_won)}")

    # Also look at top-5 overlaps
    print(f"\n  Top-5 frequency (trials appearing in top 5 across months):")
    top5_freq = defaultdict(int)
    for month, top5 in top5_per_month.items():
        for run_id, pnl in top5:
            top5_freq[run_id] += 1

    sorted_freq = sorted(top5_freq.items(), key=lambda x: x[1], reverse=True)
    print(f"  {'Trial':>8}  {'Top-5 Appearances':>18}  {'Overall P&L':>12}")
    print(f"  {'-'*8}  {'-'*18}  {'-'*12}")
    for run_id, freq in sorted_freq[:15]:
        trial = extract_trial_number(run_id)
        overall = totals.get(run_id, {}).get("total_pnl", 0)
        print(f"  #{trial:>6}  {freq:>18}  ${overall:>11.2f}")

    # =========================================================================
    section("4. DETAILED MONTHLY WINNER PROFILES")
    # =========================================================================

    for month in all_months:
        best = best_per_month[month]
        run_id = best["run_id"]
        trial = extract_trial_number(run_id)

        print(f"  --- {month} | Best: Trial #{trial} | P&L: ${best['pnl']:.2f} ---")

        # Pattern breakdown
        patterns = get_monthly_patterns(conn, run_id, month)
        if patterns:
            print(f"    Patterns:")
            for p in patterns:
                wr = (p["wins"] / p["cnt"] * 100) if p["cnt"] > 0 else 0
                print(f"      {p['pattern']:<20} {p['cnt']:>4} trades  ${p['total_pnl']:>8.2f} P&L  {wr:.0f}% WR  ${p['avg_pnl']:>6.2f} avg")

        # Detail from monthly_detail
        detail = monthly_detail.get(run_id, {}).get(month, {})
        if detail:
            trades = detail["trades"]
            winners = detail["winners"]
            losers = detail["losers"]
            wr = (winners / trades * 100) if trades > 0 else 0
            print(f"    Summary: {trades} trades, {winners}W/{losers}L, {wr:.1f}% WR")

        # Key params
        params = get_trial_params(conn, run_id)
        if params:
            enabled_patterns = [k.replace("b_enable_", "") for k, v in params.items()
                              if k.startswith("b_enable_") and v and k not in ("b_enable_ema9", "b_enable_macd", "b_enable_trend", "b_enable_rr")]
            enabled_filters = [k.replace("a_enable_", "") for k, v in params.items()
                             if k.startswith("a_enable_") and v]
            print(f"    Patterns enabled: {', '.join(enabled_patterns)}")
            print(f"    Filters enabled: {', '.join(enabled_filters)}")
            print(f"    Price range: ${params.get('a_min_price', 0):.2f}-${params.get('a_max_price', 0):.2f}")
            print(f"    Min premarket gain: {params.get('a_min_premarket_gain', 0):.1f}%")
            print(f"    Stop buffer: {params.get('b_stop_buffer', 0):.4f}")
            print(f"    T1 ratio: {params.get('c_target1_ratio', 0):.2f}, T2 ratio: {params.get('c_target2_ratio', 0):.2f}")
            print(f"    Trailing stop: {params.get('c_trailing_stop_distance', 0):.3f}")
        print()

    # =========================================================================
    section("5. REGIME GROUPING: Clustering months by winner characteristics")
    # =========================================================================

    # For each month's winner, extract key config dimensions
    regime_data = []
    for month in all_months:
        best = best_per_month[month]
        run_id = best["run_id"]
        params = get_trial_params(conn, run_id)
        detail = monthly_detail.get(run_id, {}).get(month, {})
        patterns = get_monthly_patterns(conn, run_id, month)

        if not params:
            continue

        # Extract features for clustering
        enabled_patterns = [k.replace("b_enable_", "") for k, v in params.items()
                          if k.startswith("b_enable_") and v and k not in ("b_enable_ema9", "b_enable_macd", "b_enable_trend", "b_enable_rr")]

        # Dominant pattern (by P&L contribution)
        dominant_pattern = "NONE"
        if patterns:
            dominant_pattern = patterns[0]["pattern"]  # already sorted by pnl desc

        regime_data.append({
            "month": month,
            "trial": extract_trial_number(run_id),
            "pnl": best["pnl"],
            "trades": detail.get("trades", 0),
            "win_rate": (detail.get("winners", 0) / detail.get("trades", 1)) * 100,
            "dominant_pattern": dominant_pattern,
            "num_patterns": len(enabled_patterns),
            "patterns": enabled_patterns,
            "stop_buffer": params.get("b_stop_buffer", 0),
            "trailing_stop": params.get("c_trailing_stop_distance", 0),
            "t1_ratio": params.get("c_target1_ratio", 0),
            "min_gain": params.get("a_min_premarket_gain", 0),
            "price_range": f"${params.get('a_min_price', 0):.1f}-${params.get('a_max_price', 0):.1f}",
        })

    # Try to identify natural groupings
    # Group 1: By trade frequency (conservative vs aggressive)
    print("  A) By Trade Frequency (Monthly):")
    print(f"    {'Month':>8}  {'Trial':>6}  {'Trades':>7}  {'P&L':>9}  {'WR%':>5}  {'Dominant Pattern':>20}  {'Style'}")
    print(f"    {'-'*8}  {'-'*6}  {'-'*7}  {'-'*9}  {'-'*5}  {'-'*20}  {'-'*15}")

    for d in regime_data:
        if d["trades"] <= 5:
            style = "SNIPER"
        elif d["trades"] <= 15:
            style = "SELECTIVE"
        elif d["trades"] <= 30:
            style = "MODERATE"
        else:
            style = "AGGRESSIVE"

        print(f"    {d['month']:>8}  #{d['trial']:>5}  {d['trades']:>7}  ${d['pnl']:>8.2f}  {d['win_rate']:>4.0f}%  {d['dominant_pattern']:>20}  {style}")

    # Group 2: By dominant pattern
    print(f"\n  B) By Dominant Pattern:")
    pattern_groups = defaultdict(list)
    for d in regime_data:
        pattern_groups[d["dominant_pattern"]].append(d)

    for pattern, months in sorted(pattern_groups.items(), key=lambda x: -len(x[1])):
        total_pnl = sum(d["pnl"] for d in months)
        avg_pnl = total_pnl / len(months) if months else 0
        month_list = ", ".join(d["month"] for d in months)
        print(f"    {pattern:<20} | {len(months)} months | Total: ${total_pnl:>8.2f} | Avg: ${avg_pnl:>8.2f}")
        print(f"      Months: {month_list}")

    # Group 3: By stop tightness (tight vs loose)
    print(f"\n  C) By Stop Tightness (trailing_stop distance):")
    tight = [d for d in regime_data if d["trailing_stop"] < 0.15]
    medium = [d for d in regime_data if 0.15 <= d["trailing_stop"] < 0.35]
    loose = [d for d in regime_data if d["trailing_stop"] >= 0.35]

    for label, group in [("TIGHT (<0.15)", tight), ("MEDIUM (0.15-0.35)", medium), ("LOOSE (>=0.35)", loose)]:
        if group:
            total_pnl = sum(d["pnl"] for d in group)
            months = ", ".join(d["month"] for d in group)
            print(f"    {label:<25} | {len(group)} months | Total: ${total_pnl:>8.2f} | Months: {months}")

    # =========================================================================
    section("6. CROSS-TRIAL MONTHLY CORRELATION HEATMAP (text)")
    # =========================================================================

    # For the top 10 overall trials, show their monthly P&L side by side
    top10_runs = [run_id for run_id, _ in sorted_totals[:10]]

    # Header
    header = f"  {'Month':>8}"
    for run_id in top10_runs:
        trial = extract_trial_number(run_id)
        header += f"  #{trial:>6}"
    header += f"  {'BEST':>8}"
    print(header)
    print(f"  {'-'*8}" + f"  {'-'*7}" * len(top10_runs) + f"  {'-'*8}")

    for month in all_months:
        row = f"  {month:>8}"
        for run_id in top10_runs:
            pnl = monthly.get(run_id, {}).get(month, 0)
            if pnl >= 100:
                row += f"  ${pnl:>5.0f}+"
            elif pnl >= 0:
                row += f"  ${pnl:>6.0f}"
            else:
                row += f"  ${pnl:>6.0f}"
        best = best_per_month[month]
        row += f"  ${best['pnl']:>7.0f}"
        print(row)

    # Totals
    row = f"  {'TOTAL':>8}"
    for run_id in top10_runs:
        total = sum(monthly.get(run_id, {}).get(m, 0) for m in all_months)
        row += f"  ${total:>6.0f}"
    row += f"  ${composite_pnl:>7.0f}"
    print(f"  {'-'*8}" + f"  {'-'*7}" * len(top10_runs) + f"  {'-'*8}")
    print(row)

    # =========================================================================
    section("7. 'WORST MONTH' ANALYSIS: Where does Trial 198 struggle?")
    # =========================================================================

    t198_months = sorted(t198_monthly.items(), key=lambda x: x[1])
    print(f"  Trial 198 worst months:")
    print(f"  {'Month':>8}  {'T198 P&L':>10}  {'Best Trial':>11}  {'Best P&L':>10}  {'Gap':>10}")
    print(f"  {'-'*8}  {'-'*10}  {'-'*11}  {'-'*10}  {'-'*10}")
    for month, pnl in t198_months:
        best = best_per_month.get(month, {"run_id": "N/A", "pnl": 0})
        trial = extract_trial_number(best["run_id"]) if best["run_id"] != "N/A" else "N/A"
        gap = best["pnl"] - pnl
        print(f"  {month:>8}  ${pnl:>9.2f}  #{trial:>9}  ${best['pnl']:>9.2f}  ${gap:>+9.2f}")

    # =========================================================================
    section("8. POTENTIAL REGIME DETECTOR FEATURES")
    # =========================================================================

    # Analyze what differs between months where different configs win
    print("  Key insight: What config features vary most between monthly winners?\n")

    # Collect all winner configs
    config_features = []
    for month in all_months:
        run_id = best_per_month[month]["run_id"]
        params = get_trial_params(conn, run_id)
        if params:
            config_features.append({
                "month": month,
                "trial": extract_trial_number(run_id),
                "stop_buffer": params.get("b_stop_buffer", 0),
                "trailing_stop": params.get("c_trailing_stop_distance", 0),
                "t1_ratio": params.get("c_target1_ratio", 0),
                "t2_ratio": params.get("c_target2_ratio", 0),
                "t1_qty": params.get("c_target1_qty_pct", 0),
                "min_gain": params.get("a_min_premarket_gain", 0),
                "min_rr": params.get("b_min_rr_ratio", 0),
                "selling_pressure": params.get("c_selling_pressure_ratio", 0),
                "bull_flag": params.get("b_enable_bull_flag", False),
                "micro_pb": params.get("b_enable_micro_pullback", False),
                "abcd": params.get("b_enable_abcd", False),
                "flat_top": params.get("b_enable_flat_top", False),
                "dip_buy": params.get("b_enable_dip_buy", False),
            })

    # Show the feature table
    print(f"  {'Month':>8}  {'Trial':>6}  {'StopBuf':>8}  {'Trail':>6}  {'T1R':>5}  {'T2R':>5}  {'MinGn%':>7}  {'RR':>5}  {'BF':>3}  {'MP':>3}  {'AB':>3}  {'FT':>3}  {'DB':>3}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*5}  {'-'*7}  {'-'*5}  {'-'*3}  {'-'*3}  {'-'*3}  {'-'*3}  {'-'*3}")

    for cf in config_features:
        bf = "Y" if cf["bull_flag"] else "-"
        mp = "Y" if cf["micro_pb"] else "-"
        ab = "Y" if cf["abcd"] else "-"
        ft = "Y" if cf["flat_top"] else "-"
        db = "Y" if cf["dip_buy"] else "-"
        print(f"  {cf['month']:>8}  #{cf['trial']:>5}  {cf['stop_buffer']:>8.4f}  {cf['trailing_stop']:>6.3f}  {cf['t1_ratio']:>5.2f}  {cf['t2_ratio']:>5.2f}  {cf['min_gain']:>6.1f}%  {cf['min_rr']:>5.2f}  {bf:>3}  {mp:>3}  {ab:>3}  {ft:>3}  {db:>3}")

    # Compute variance/range for each feature
    print(f"\n  Feature variability across monthly winners:")
    if config_features:
        numeric_keys = ["stop_buffer", "trailing_stop", "t1_ratio", "t2_ratio", "t1_qty", "min_gain", "min_rr", "selling_pressure"]
        for key in numeric_keys:
            values = [cf[key] for cf in config_features]
            mn, mx = min(values), max(values)
            avg = sum(values) / len(values)
            spread = mx - mn
            print(f"    {key:<22}  min={mn:.4f}  max={mx:.4f}  avg={avg:.4f}  spread={spread:.4f}")

    # =========================================================================
    section("9. SUMMARY & RECOMMENDATIONS")
    # =========================================================================

    print(f"  1. CEILING: A perfect regime detector would yield ${composite_pnl:,.2f}")
    print(f"     vs Trial 198's flat ${trial_198_total:,.2f} = {((composite_pnl / trial_198_total - 1) * 100) if trial_198_total != 0 else 0:.0f}% improvement")
    print()

    unique_winners = len(winner_counts)
    if unique_winners <= 4:
        print(f"  2. CLUSTER TIGHTNESS: Only {unique_winners} unique winners across {len(all_months)} months")
        print(f"     -> Few configs dominate -> regime detection may be simple (2-3 modes)")
    elif unique_winners <= 8:
        print(f"  2. CLUSTER TIGHTNESS: {unique_winners} unique winners across {len(all_months)} months")
        print(f"     -> Moderate diversity -> regime detection feasible with ~3-4 modes")
    else:
        print(f"  2. CLUSTER TIGHTNESS: {unique_winners} unique winners across {len(all_months)} months")
        print(f"     -> High diversity -> every month is different; regime detection is hard")
    print()

    # Check if any trial appears in top-5 consistently
    consistent_trials = [(run_id, freq) for run_id, freq in sorted_freq if freq >= len(all_months) * 0.5]
    if consistent_trials:
        print(f"  3. CONSISTENT PERFORMERS (top-5 in >50% of months):")
        for run_id, freq in consistent_trials:
            trial = extract_trial_number(run_id)
            pnl = totals.get(run_id, {}).get("total_pnl", 0)
            print(f"     Trial #{trial}: top-5 in {freq}/{len(all_months)} months, overall P&L: ${pnl:,.2f}")
    else:
        print(f"  3. No trial appears in top-5 for >50% of months")
        print(f"     -> Confirms regime-switching is more valuable than finding one config")
    print()

    # Pattern regime suggestion
    print(f"  4. PATTERN-BASED REGIME SUGGESTION:")
    for pattern, months in sorted(pattern_groups.items(), key=lambda x: -len(x[1])):
        month_list = [d["month"] for d in months]
        print(f"     {pattern}: dominates in {month_list}")

    conn.close()


if __name__ == "__main__":
    main()
