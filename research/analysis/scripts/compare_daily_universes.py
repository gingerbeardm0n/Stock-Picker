#!/usr/bin/env python3
"""
Compare daily_gaprun_universe vs pillar23_universe day-by-day.

For each date that appears in pillar23:
  - Get the N pillar23 symbols for that date
  - Get the top-N daily gap-run symbols (matching N for a fair comparison)
  - Compute overlap and differences

Also reports aggregate stats and identifies symbols that are unique to each list.

Usage:
  python analysis/compare_daily_universes.py
  python analysis/compare_daily_universes.py --gaprun analysis/daily_gaprun_universe.csv
  python analysis/compare_daily_universes.py --output analysis/universe_comparison.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load_pillar23(path: Path) -> dict[str, set[str]]:
    """Load pillar23_universe.csv → {date_str: set(symbols)}"""
    df = pd.read_csv(path, dtype=str).dropna(subset=["date", "symbol"])
    result: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        result.setdefault(row["date"].strip(), set()).add(row["symbol"].strip())
    return result


def load_gaprun(path: Path) -> dict[str, list[str]]:
    """Load daily_gaprun_universe.csv → {date_str: [symbols in rank order]}"""
    df = pd.read_csv(path, dtype={"date": str, "symbol": str, "rank": int,
                                   "max_run_gain_pct": float, "gaprun_count": int})
    df = df.dropna(subset=["date", "symbol"])
    df = df.sort_values(["date", "rank"])
    result: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        result.setdefault(row["date"].strip(), []).append(row["symbol"].strip())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare daily gap-run universe vs pillar23 universe"
    )
    parser.add_argument("--pillar23", default="analysis/pillar23_universe.csv",
                        help="Path to pillar23_universe.csv")
    parser.add_argument("--gaprun", default="analysis/daily_gaprun_universe.csv",
                        help="Path to daily_gaprun_universe.csv")
    parser.add_argument("--output", default="analysis/universe_comparison.csv",
                        help="Path for per-day comparison CSV output")
    args = parser.parse_args()

    p23_path = Path(args.pillar23)
    gr_path = Path(args.gaprun)

    if not p23_path.exists():
        raise SystemExit(f"ERROR: {p23_path} not found. Run analysis/create_pillar23_universe.py first.")
    if not gr_path.exists():
        raise SystemExit(f"ERROR: {gr_path} not found. Run database/generate_daily_gaprun_universe.py first.")

    p23 = load_pillar23(p23_path)
    gr = load_gaprun(gr_path)

    print("=" * 65)
    print("  DAILY UNIVERSE COMPARISON: GAP-RUN vs PILLAR23")
    print("=" * 65)
    print(f"  Pillar23 file : {p23_path}")
    print(f"  Gap-run file  : {gr_path}")
    print()

    # Overall sizes
    p23_total_rows = sum(len(v) for v in p23.values())
    gr_total_rows = sum(len(v) for v in gr.values())
    p23_all_syms = set(s for syms in p23.values() for s in syms)
    gr_all_syms = set(s for syms in gr.values() for s in syms)

    print(f"  Pillar23 : {p23_total_rows:,} date-symbol rows, "
          f"{len(p23)} dates, {len(p23_all_syms):,} unique symbols")
    print(f"  Gap-run  : {gr_total_rows:,} date-symbol rows, "
          f"{len(gr)} dates, {len(gr_all_syms):,} unique symbols")
    print()

    # All-time unique overlap
    both_syms = p23_all_syms & gr_all_syms
    p23_only_syms = p23_all_syms - gr_all_syms
    gr_only_syms = gr_all_syms - p23_all_syms
    print(f"  All-time unique symbol overlap:")
    print(f"    In both            : {len(both_syms):,}  "
          f"({len(both_syms)/len(p23_all_syms)*100:.1f}% of pillar23, "
          f"{len(both_syms)/len(gr_all_syms)*100:.1f}% of gap-run)")
    print(f"    Pillar23 only      : {len(p23_only_syms):,}")
    print(f"    Gap-run only       : {len(gr_only_syms):,}")
    print()

    # Per-day comparison
    common_dates = sorted(set(p23.keys()) & set(gr.keys()))
    p23_dates_no_gr = sorted(set(p23.keys()) - set(gr.keys()))
    gr_dates_no_p23 = sorted(set(gr.keys()) - set(p23.keys()))

    print(f"  Dates in pillar23       : {len(p23)}")
    print(f"  Dates in gap-run        : {len(gr)}")
    print(f"  Dates in both           : {len(common_dates)}")
    if p23_dates_no_gr:
        print(f"  Pillar23 dates w/o gaprun: {len(p23_dates_no_gr)} "
              f"(e.g. {p23_dates_no_gr[:3]})")
    if gr_dates_no_p23:
        print(f"  Gap-run dates w/o p23   : {len(gr_dates_no_p23)}")
    print()

    # Per-day stats
    comparison_rows = []
    overlap_pcts = []

    for date_str in common_dates:
        p23_syms = p23[date_str]
        gr_ranked = gr[date_str]
        n = len(p23_syms)

        # Take top-N gap-run symbols to match pillar23 count
        gr_top_n = set(gr_ranked[:n])

        overlap = p23_syms & gr_top_n
        p23_only = p23_syms - gr_top_n
        gr_only = gr_top_n - p23_syms
        overlap_pct = len(overlap) / n * 100 if n > 0 else 0.0

        overlap_pcts.append(overlap_pct)
        comparison_rows.append({
            "date": date_str,
            "p23_count": n,
            "gr_topn_count": len(gr_top_n),
            "overlap": len(overlap),
            "overlap_pct": round(overlap_pct, 1),
            "p23_only_count": len(p23_only),
            "gr_only_count": len(gr_only),
            "p23_symbols": "|".join(sorted(p23_syms)),
            "gr_top_symbols": "|".join(gr_ranked[:n]),
            "overlap_symbols": "|".join(sorted(overlap)),
            "p23_only_symbols": "|".join(sorted(p23_only)),
            "gr_only_symbols": "|".join(sorted(gr_only)),
        })

    if not overlap_pcts:
        print("  WARNING: No common dates found between the two universes.")
        return

    import statistics
    mean_overlap = statistics.mean(overlap_pcts)
    median_overlap = statistics.median(overlap_pcts)
    high_overlap_days = sum(1 for p in overlap_pcts if p >= 50)
    low_overlap_days = sum(1 for p in overlap_pcts if p < 20)
    zero_overlap_days = sum(1 for p in overlap_pcts if p == 0)

    avg_p23_per_day = sum(r["p23_count"] for r in comparison_rows) / len(comparison_rows)

    print(f"  Per-day overlap (comparing top-N gap-run to N pillar23 symbols):")
    print(f"    Common dates analyzed : {len(common_dates)}")
    print(f"    Avg pillar23/day      : {avg_p23_per_day:.1f} symbols")
    print(f"    Mean overlap          : {mean_overlap:.1f}%")
    print(f"    Median overlap        : {median_overlap:.1f}%")
    print(f"    Days with >=50% overlap : {high_overlap_days} ({high_overlap_days/len(common_dates)*100:.0f}%)")
    print(f"    Days with <20% overlap  : {low_overlap_days} ({low_overlap_days/len(common_dates)*100:.0f}%)")
    print(f"    Days with 0% overlap    : {zero_overlap_days} ({zero_overlap_days/len(common_dates)*100:.0f}%)")
    print()

    # Best and worst overlap days
    comp_df = pd.DataFrame(comparison_rows)
    print("  Best overlap days (top 5):")
    for _, row in comp_df.nlargest(5, "overlap_pct").iterrows():
        print(f"    {row['date']}  {row['overlap_pct']:.0f}%  "
              f"({row['overlap']}/{row['p23_count']})  overlap: {row['overlap_symbols'][:60]}")

    print()
    print("  Worst overlap days (bottom 5, excluding 0-symbol days):")
    nonzero = comp_df[comp_df["p23_count"] > 1]
    for _, row in nonzero.nsmallest(5, "overlap_pct").iterrows():
        print(f"    {row['date']}  {row['overlap_pct']:.0f}%  "
              f"({row['overlap']}/{row['p23_count']})  "
              f"p23_only: {row['p23_only_symbols'][:40]}  "
              f"gr_only: {row['gr_only_symbols'][:40]}")
    print()

    # Symbols most frequently in gap-run but NOT in pillar23 (candidate for investigation)
    gr_sym_freq: dict[str, int] = {}
    p23_sym_dates: dict[str, int] = {}
    for row in comparison_rows:
        for s in row["gr_only_symbols"].split("|"):
            if s:
                gr_sym_freq[s] = gr_sym_freq.get(s, 0) + 1
        for s in row["p23_symbols"].split("|"):
            if s:
                p23_sym_dates[s] = p23_sym_dates.get(s, 0) + 1

    top_gr_only = sorted(gr_sym_freq.items(), key=lambda x: -x[1])[:15]
    print(f"  Top gap-run symbols that rarely/never appear in pillar23:")
    print(f"  (these ran well 9:30-11am but didn't pass premarket Pillar 2+3)")
    for sym, cnt in top_gr_only:
        print(f"    {sym:<8s}  appears in {cnt} gap-run days (not in pillar23 on those days)")
    print()

    # Symbols most frequently in pillar23 but NOT in gap-run top-N
    p23_only_freq: dict[str, int] = {}
    for row in comparison_rows:
        for s in row["p23_only_symbols"].split("|"):
            if s:
                p23_only_freq[s] = p23_only_freq.get(s, 0) + 1
    top_p23_only = sorted(p23_only_freq.items(), key=lambda x: -x[1])[:15]
    print(f"  Top pillar23 symbols that rarely/never appear in gap-run top-N:")
    print(f"  (these passed premarket filters but didn't run hard 9:30-11am)")
    for sym, cnt in top_p23_only:
        print(f"    {sym:<8s}  in pillar23 {cnt} times but not in gap-run top-N")
    print()

    # Write per-day comparison CSV (without the long symbol columns for readability)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Full version with symbol lists
    comp_df.to_csv(out_path, index=False)
    # Summary version without symbol lists for easy viewing
    summary_path = out_path.with_stem(out_path.stem + "_summary")
    comp_df.drop(columns=["p23_symbols", "gr_top_symbols", "overlap_symbols",
                           "p23_only_symbols", "gr_only_symbols"]).to_csv(
        summary_path, index=False
    )
    print(f"  Written: {out_path}  (full, includes symbol lists)")
    print(f"  Written: {summary_path}  (summary, numeric only)")
    print()
    print("  Done.")


if __name__ == "__main__":
    main()
