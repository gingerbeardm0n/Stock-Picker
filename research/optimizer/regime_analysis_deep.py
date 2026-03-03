#!/usr/bin/env python3
"""
Deep Regime Analysis - Part 2
==============================
Builds on the initial analysis with:
1. Realistic composite (exclude overall-negative trials from monthly picks)
2. 2-regime and 3-regime grouping proposals
3. Month-over-month consistency analysis
4. Detailed config diff between regimes
"""

import sqlite3
import json
from collections import defaultdict
from pathlib import Path
import math

DB_PATH = Path(__file__).parent / "robust_results.db"


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def extract_trial_number(run_id: str) -> int:
    return int(run_id.split("_")[1])


def section(title: str):
    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}\n")


def main():
    conn = get_connection()
    cur = conn.cursor()

    # ---- Load all monthly P&L data ----
    cur.execute("""
        SELECT run_id,
               strftime('%Y-%m', date) as month,
               SUM(pnl) as month_pnl,
               COUNT(*) as trade_count,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as winners
        FROM trades
        GROUP BY run_id, strftime('%Y-%m', date)
        ORDER BY run_id, month
    """)

    monthly = defaultdict(dict)  # {run_id: {month: pnl}}
    monthly_detail = defaultdict(dict)
    for row in cur.fetchall():
        monthly[row["run_id"]][row["month"]] = row["month_pnl"]
        monthly_detail[row["run_id"]][row["month"]] = {
            "pnl": row["month_pnl"],
            "trades": row["trade_count"],
            "winners": row["winners"],
        }

    # Get overall trial info
    cur.execute("SELECT run_id, total_pnl, total_trades, params_json FROM runs ORDER BY total_pnl DESC")
    runs_data = {}
    for row in cur.fetchall():
        runs_data[row["run_id"]] = {
            "total_pnl": row["total_pnl"],
            "total_trades": row["total_trades"],
            "params": json.loads(row["params_json"]),
        }

    all_months = sorted(set(m for months in monthly.values() for m in months))
    # Exclude 2026-02 if it has no real data
    all_months = [m for m in all_months if m != "2026-02"]

    # =========================================================================
    section("A. REALISTIC COMPOSITE: Best per month (only trials profitable overall)")
    # =========================================================================

    # Filter: only trials with overall P&L > 0
    profitable_runs = {r for r, d in runs_data.items() if d["total_pnl"] > 0}
    print(f"  Profitable trials: {len(profitable_runs)} out of {len(runs_data)}")

    # Also tier: strongly profitable (>$500), moderately profitable (>$0)
    strong_runs = {r for r, d in runs_data.items() if d["total_pnl"] > 500}
    print(f"  Strongly profitable (>$500): {len(strong_runs)}")

    for label, run_set in [("ALL trials", set(runs_data.keys())), ("Profitable only (>$0)", profitable_runs), ("Strong only (>$500)", strong_runs)]:
        composite = 0
        print(f"\n  --- {label} ---")
        print(f"  {'Month':>8}  {'Best Trial':>11}  {'Best P&L':>10}  {'Overall P&L':>12}  {'Trades':>7}")
        print(f"  {'-'*8}  {'-'*11}  {'-'*10}  {'-'*12}  {'-'*7}")

        for month in all_months:
            best_run = None
            best_pnl = float("-inf")
            for run_id in run_set:
                pnl = monthly.get(run_id, {}).get(month, 0)
                if pnl > best_pnl:
                    best_pnl = pnl
                    best_run = run_id
            composite += best_pnl
            trial = extract_trial_number(best_run) if best_run else -1
            overall = runs_data.get(best_run, {}).get("total_pnl", 0)
            trades = monthly_detail.get(best_run, {}).get(month, {}).get("trades", 0)
            print(f"  {month:>8}  #{trial:>9}  ${best_pnl:>9.2f}  ${overall:>11.2f}  {trades:>7}")

        print(f"  {'TOTAL':>8}  {'':>11}  ${composite:>9.2f}")

    # =========================================================================
    section("B. PATTERN-BASED REGIME PROPOSAL (3 regimes)")
    # =========================================================================

    # From initial analysis:
    # FLAT_TOP dominates 8/13 months
    # MICRO_PULLBACK dominates 2/13 months
    # ABCD dominates 2/13 months
    # BULL_FLAG dominates 1/13 months

    # Proposal: 3 regimes
    # 1. FLAT_TOP regime (high-volume breakouts): Jan, Feb, Jun, Aug, Sep, Oct, Dec, Jan'26
    # 2. PULLBACK regime (micro pullback / ABCD): Mar, Apr, May, Jul
    # 3. REVERSAL regime (bull flag / dip buy): Nov

    print("  Proposed 3-Regime Model:")
    print("  ========================")
    print()

    regimes = {
        "BREAKOUT (FLAT_TOP)": ["2025-01", "2025-02", "2025-06", "2025-08", "2025-09", "2025-10", "2025-12", "2026-01"],
        "PULLBACK (MICRO_PB/ABCD)": ["2025-03", "2025-04", "2025-05", "2025-07"],
        "REVERSAL (BULL_FLAG)": ["2025-11"],
    }

    # For each regime, find the BEST SINGLE trial across its months
    for regime_name, regime_months in regimes.items():
        print(f"  REGIME: {regime_name}")
        print(f"  Months: {', '.join(regime_months)}")

        # Score each trial by sum of P&L in regime months only
        trial_scores = {}
        for run_id in runs_data:
            score = sum(monthly.get(run_id, {}).get(m, 0) for m in regime_months)
            trades = sum(monthly_detail.get(run_id, {}).get(m, {}).get("trades", 0) for m in regime_months)
            trial_scores[run_id] = {"pnl": score, "trades": trades}

        sorted_scores = sorted(trial_scores.items(), key=lambda x: x[1]["pnl"], reverse=True)

        print(f"\n  Top 10 trials for this regime:")
        print(f"  {'Trial':>8}  {'Regime P&L':>11}  {'Trades':>7}  {'Overall P&L':>12}  {'P&L/Trade':>10}")
        print(f"  {'-'*8}  {'-'*11}  {'-'*7}  {'-'*12}  {'-'*10}")

        for run_id, data in sorted_scores[:10]:
            trial = extract_trial_number(run_id)
            overall = runs_data[run_id]["total_pnl"]
            ppt = data["pnl"] / data["trades"] if data["trades"] > 0 else 0
            print(f"  #{trial:>6}  ${data['pnl']:>10.2f}  {data['trades']:>7}  ${overall:>11.2f}  ${ppt:>9.2f}")

        # Show monthly breakdown for top 3
        print(f"\n  Monthly breakdown of top 3:")
        for run_id, data in sorted_scores[:3]:
            trial = extract_trial_number(run_id)
            row = f"    #{trial:>5}: "
            for m in regime_months:
                pnl = monthly.get(run_id, {}).get(m, 0)
                row += f" {m}=${pnl:>7.0f}"
            row += f"  | Total=${data['pnl']:>.0f}"
            print(row)

        print()

    # =========================================================================
    section("C. 3-REGIME COMPOSITE: Best single trial per regime")
    # =========================================================================

    # Pick the best trial for each regime and calculate combined P&L
    print("  If we use ONE config per regime (best trial for that regime's months):\n")

    regime_composite = 0
    regime_picks = {}

    for regime_name, regime_months in regimes.items():
        # Find best trial restricted to profitable trials
        best_run = None
        best_score = float("-inf")
        for run_id in profitable_runs:
            score = sum(monthly.get(run_id, {}).get(m, 0) for m in regime_months)
            if score > best_score:
                best_score = score
                best_run = run_id

        regime_picks[regime_name] = {"run_id": best_run, "pnl": best_score}
        regime_composite += best_score

        trial = extract_trial_number(best_run)
        print(f"  {regime_name}")
        print(f"    Best trial: #{trial}")
        print(f"    Regime P&L: ${best_score:,.2f}")

        # Show monthly
        for m in regime_months:
            pnl = monthly.get(best_run, {}).get(m, 0)
            trades = monthly_detail.get(best_run, {}).get(m, {}).get("trades", 0)
            print(f"      {m}: ${pnl:>8.2f}  ({trades} trades)")
        print()

    print(f"  3-REGIME COMPOSITE TOTAL: ${regime_composite:,.2f}")
    t198_total = sum(monthly.get("optuna_00198", {}).get(m, 0) for m in all_months)
    print(f"  Trial 198 flat total:     ${t198_total:,.2f}")
    print(f"  Improvement:              ${regime_composite - t198_total:,.2f} ({((regime_composite / t198_total - 1) * 100) if t198_total else 0:.0f}%)")

    # =========================================================================
    section("D. CONFIG DIFF BETWEEN REGIME WINNERS")
    # =========================================================================

    print("  Key parameter differences between regime-specific best trials:\n")

    # Collect params for each regime's top pick
    regime_params = {}
    for regime_name, pick in regime_picks.items():
        run_id = pick["run_id"]
        trial = extract_trial_number(run_id)
        params = runs_data[run_id]["params"]
        regime_params[regime_name] = {"trial": trial, "params": params}

    # Important config keys to compare
    compare_keys = [
        ("PATTERNS", [
            "b_enable_bull_flag", "b_enable_micro_pullback", "b_enable_abcd",
            "b_enable_dip_buy", "b_enable_flat_top",
        ]),
        ("ENTRY FILTERS", [
            "a_min_price", "a_max_price", "a_min_premarket_gain",
            "a_enable_relative_volume", "a_enable_buying_volume",
            "a_enable_float_filter", "a_enable_market_cap_filter",
        ]),
        ("STOPS & TARGETS", [
            "b_stop_buffer", "b_min_rr_ratio",
            "c_target1_ratio", "c_target2_ratio",
            "c_target1_qty_pct", "c_target2_qty_pct",
            "c_trailing_stop_distance",
        ]),
        ("EXIT SIGNALS", [
            "c_selling_pressure_ratio", "c_selling_pressure_qty_pct",
            "c_enable_macd_flip_exit", "c_enable_resistance_exit",
            "c_enable_volume_dry_up_exit",
        ]),
    ]

    # Header
    regime_labels = list(regime_params.keys())
    short_labels = ["BREAKOUT", "PULLBACK", "REVERSAL"]

    for group_name, keys in compare_keys:
        print(f"  --- {group_name} ---")
        header = f"  {'Parameter':<35}"
        for sl in short_labels:
            header += f"  {sl:>12}"
        print(header)
        print(f"  {'-'*35}" + f"  {'-'*12}" * len(short_labels))

        for key in keys:
            row = f"  {key:<35}"
            for rn in regime_labels:
                val = regime_params[rn]["params"].get(key, "N/A")
                if isinstance(val, bool):
                    row += f"  {'YES':>12}" if val else f"  {'no':>12}"
                elif isinstance(val, float):
                    row += f"  {val:>12.4f}"
                else:
                    row += f"  {str(val):>12}"
            print(row)
        print()

    # =========================================================================
    section("E. MONTH-BY-MONTH PERFORMANCE: 3-Regime vs Trial 198 vs Perfect")
    # =========================================================================

    print(f"  {'Month':>8}  {'Regime':>22}  {'Regime P&L':>11}  {'T198 P&L':>9}  {'Perfect':>8}  {'Regime Pick':>12}")
    print(f"  {'-'*8}  {'-'*22}  {'-'*11}  {'-'*9}  {'-'*8}  {'-'*12}")

    total_regime = 0
    total_198 = 0
    total_perfect = 0

    for month in all_months:
        # Which regime is this month in?
        regime_name = None
        for rn, months in regimes.items():
            if month in months:
                regime_name = rn
                break

        if regime_name is None:
            continue

        pick = regime_picks[regime_name]
        regime_pnl = monthly.get(pick["run_id"], {}).get(month, 0)
        t198_pnl = monthly.get("optuna_00198", {}).get(month, 0)

        # Perfect: best of any trial
        best_pnl = max(monthly.get(r, {}).get(month, 0) for r in runs_data)

        trial = extract_trial_number(pick["run_id"])
        short_regime = regime_name.split("(")[0].strip()

        total_regime += regime_pnl
        total_198 += t198_pnl
        total_perfect += best_pnl

        print(f"  {month:>8}  {short_regime:>22}  ${regime_pnl:>10.2f}  ${t198_pnl:>8.2f}  ${best_pnl:>7.0f}  #{trial}")

    print(f"  {'-'*8}  {'-'*22}  {'-'*11}  {'-'*9}  {'-'*8}  {'-'*12}")
    print(f"  {'TOTAL':>8}  {'':>22}  ${total_regime:>10.2f}  ${total_198:>8.2f}  ${total_perfect:>7.0f}")
    print()
    print(f"  3-Regime captures {(total_regime/total_perfect*100) if total_perfect else 0:.1f}% of the perfect ceiling")
    print(f"  Trial 198 captures {(total_198/total_perfect*100) if total_perfect else 0:.1f}% of the perfect ceiling")

    # =========================================================================
    section("F. SIMPLIFIED 2-REGIME MODEL: FLAT_TOP months vs non-FLAT_TOP months")
    # =========================================================================

    ft_months = ["2025-01", "2025-02", "2025-06", "2025-08", "2025-09", "2025-10", "2025-12", "2026-01"]
    non_ft_months = [m for m in all_months if m not in ft_months]

    print(f"  FLAT_TOP months ({len(ft_months)}): {', '.join(ft_months)}")
    print(f"  Non-FLAT_TOP months ({len(non_ft_months)}): {', '.join(non_ft_months)}")
    print()

    # Best trial for each regime (from profitable trials only)
    for label, months_set in [("FLAT_TOP regime", ft_months), ("NON-FLAT_TOP regime", non_ft_months)]:
        print(f"  --- {label} ---")
        best_scores = []
        for run_id in profitable_runs:
            score = sum(monthly.get(run_id, {}).get(m, 0) for m in months_set)
            trades = sum(monthly_detail.get(run_id, {}).get(m, {}).get("trades", 0) for m in months_set)
            best_scores.append((run_id, score, trades))

        best_scores.sort(key=lambda x: x[1], reverse=True)

        print(f"  {'Trial':>8}  {'P&L':>10}  {'Trades':>7}  {'Overall':>10}")
        print(f"  {'-'*8}  {'-'*10}  {'-'*7}  {'-'*10}")
        for run_id, score, trades in best_scores[:5]:
            trial = extract_trial_number(run_id)
            overall = runs_data[run_id]["total_pnl"]
            print(f"  #{trial:>6}  ${score:>9.2f}  {trades:>7}  ${overall:>9.2f}")
        print()

    # Calculate 2-regime composite
    best_ft_run = max(profitable_runs, key=lambda r: sum(monthly.get(r, {}).get(m, 0) for m in ft_months))
    best_nft_run = max(profitable_runs, key=lambda r: sum(monthly.get(r, {}).get(m, 0) for m in non_ft_months))

    ft_pnl = sum(monthly.get(best_ft_run, {}).get(m, 0) for m in ft_months)
    nft_pnl = sum(monthly.get(best_nft_run, {}).get(m, 0) for m in non_ft_months)

    ft_trial = extract_trial_number(best_ft_run)
    nft_trial = extract_trial_number(best_nft_run)

    print(f"  2-REGIME COMPOSITE:")
    print(f"    FLAT_TOP regime (#{ft_trial}):     ${ft_pnl:>9.2f}")
    print(f"    NON-FLAT_TOP regime (#{nft_trial}): ${nft_pnl:>9.2f}")
    print(f"    TOTAL:                          ${ft_pnl + nft_pnl:>9.2f}")
    print(f"    vs Trial 198:                   ${t198_total:>9.2f} ({((ft_pnl + nft_pnl) / t198_total - 1) * 100 if t198_total else 0:.0f}% improvement)")

    # =========================================================================
    section("G. STABILITY CHECK: How many months does each regime-pick WIN or LOSE?")
    # =========================================================================

    for label, run_id, months_set in [
        (f"FLAT_TOP regime (#{ft_trial})", best_ft_run, ft_months),
        (f"NON-FLAT_TOP regime (#{nft_trial})", best_nft_run, non_ft_months),
        ("Trial 198 (flat)", "optuna_00198", all_months),
    ]:
        wins = 0
        losses = 0
        for m in months_set:
            pnl = monthly.get(run_id, {}).get(m, 0)
            if pnl > 0:
                wins += 1
            else:
                losses += 1
        total = sum(monthly.get(run_id, {}).get(m, 0) for m in months_set)
        print(f"  {label}")
        print(f"    Profitable months: {wins}/{len(months_set)}")
        print(f"    Loss months: {losses}/{len(months_set)}")
        print(f"    Total P&L: ${total:,.2f}")
        print()

    # =========================================================================
    section("H. WHAT MARKET CONDITIONS SEPARATE REGIMES?")
    # =========================================================================

    # Analyze trade characteristics per month to look for regime indicators
    print("  Monthly market characteristics (from trade data):\n")

    print(f"  {'Month':>8}  {'#Trades':>8}  {'Avg P&L':>8}  {'WR%':>5}  {'Avg$':>7}  {'AvgHold':>8}  {'BestPattern':>15}  {'Regime'}")
    print(f"  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*5}  {'-'*7}  {'-'*8}  {'-'*15}  {'-'*10}")

    for month in all_months:
        # Get ALL trades across ALL trials for this month
        cur.execute("""
            SELECT COUNT(*) as cnt,
                   AVG(pnl) as avg_pnl,
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as wr,
                   AVG(entry_price) as avg_price,
                   AVG(hold_minutes) as avg_hold,
                   pattern,
                   SUM(pnl) as pattern_pnl
            FROM trades
            WHERE strftime('%Y-%m', date) = ?
            GROUP BY pattern
            ORDER BY pattern_pnl DESC
        """, (month,))

        rows = cur.fetchall()
        total_trades = sum(r["cnt"] for r in rows)
        total_pnl = sum(r["pattern_pnl"] for r in rows)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
        overall_wr = sum(r["wr"] * r["cnt"] for r in rows) / total_trades if total_trades > 0 else 0
        avg_price = sum(r["avg_price"] * r["cnt"] for r in rows) / total_trades if total_trades > 0 else 0
        avg_hold = sum(r["avg_hold"] * r["cnt"] for r in rows) / total_trades if total_trades > 0 else 0
        best_pattern = rows[0]["pattern"] if rows else "N/A"

        # Determine regime
        regime = "BREAKOUT" if month in ft_months else "PULLBACK"

        print(f"  {month:>8}  {total_trades:>8}  ${avg_pnl:>7.2f}  {overall_wr:>4.0f}%  ${avg_price:>6.1f}  {avg_hold:>7.1f}m  {best_pattern:>15}  {regime}")

    # =========================================================================
    section("I. ACTIONABLE RECOMMENDATIONS")
    # =========================================================================

    print("""  FINDING 1: Perfect Regime Detection Ceiling = $9,044 (vs $1,823 flat)
  -----------
  A 396% improvement is possible IF you could perfectly predict which config
  to run each month. This is the theoretical maximum.

  FINDING 2: Practical 2-Regime Model
  -----------
  Splitting into FLAT_TOP months vs non-FLAT_TOP months and using the best
  single trial for each regime captures significantly more than the flat approach.
  This requires only detecting: "Is this a FLAT_TOP breakout month or not?"

  FINDING 3: FLAT_TOP Dominates (8/13 months)
  -----------
  FLAT_TOP breakout is the dominant pattern. The best overall trials (#198, #204)
  are already FLAT_TOP-oriented. The biggest gains from regime-switching come from
  the 5 non-FLAT_TOP months (Mar, Apr, May, Jul, Nov).

  FINDING 4: Cluster Insight
  -----------
  - 11 unique monthly winners across 13 months = HIGH diversity
  - No single trial appears in top-5 for >50% of months
  - This confirms: regime-switching adds significant value

  FINDING 5: Regime Detection Signals to Investigate
  -----------
  - FLAT_TOP months: High trading volume, many candidates, breakout-friendly
  - PULLBACK months: Fewer candidates, market in consolidation or mild trend
  - REVERSAL months: Specific setups (bull flags) after pullbacks

  NEXT STEPS:
  1. Build a simple regime classifier based on first-week-of-month market data
  2. Use SPY/QQQ volatility, breadth, and gap frequency as features
  3. Backtest the 2-regime model with imperfect classification
  4. Even 60-70% regime detection accuracy would yield significant improvement""")

    conn.close()


if __name__ == "__main__":
    main()
