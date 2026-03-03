#!/usr/bin/env python3
"""
Compare old pillars vs prototype prescreen across a date range.
Outputs a CSV + plot of avg candidates/day and avg recall on top gappers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare prescreen strategies")
    parser.add_argument("--prototype", required=True, help="Prototype prescreen CSV")
    parser.add_argument("--top-gappers", required=True, help="Top gappers CSV")
    parser.add_argument("--output", default="database/audit_reports/prescreen_compare.csv")

    # Old pillars thresholds
    parser.add_argument("--old-day-gain", type=float, default=2.0)
    parser.add_argument("--old-rel-vol", type=float, default=1.5)

    # Prototype thresholds
    parser.add_argument("--pre-range-4-8", type=float, default=3.0)
    parser.add_argument("--last5-range", type=float, default=2.0)
    parser.add_argument("--pre-trade-count", type=float, default=50.0)
    parser.add_argument("--pre-vol-4-8", type=float, default=0.0)
    args = parser.parse_args()

    proto = pd.read_csv(args.prototype)
    gappers = pd.read_csv(args.top_gappers)
    gappers["trade_date"] = pd.to_datetime(gappers["trade_date"]).dt.date
    proto["trade_date"] = pd.to_datetime(proto["trade_date"]).dt.date

    gapper_sets = gappers.groupby("trade_date")["symbol"].apply(set).to_dict()

    # Old pillars candidates
    old_cand = proto[
        (proto["day_gain_pct_929plus"].fillna(-1e9) >= args.old_day_gain)
        & (proto["rel_vol_30d_929plus"].fillna(-1e9) >= args.old_rel_vol)
        & (proto["float_lt_20m"].fillna(False).astype(bool))
    ]

    # Prototype candidates
    proto_cand = proto[
        (proto["pre_range_pct_4_8"].fillna(-1e9) >= args.pre_range_4_8)
        & (proto["last5_range_pct"].fillna(-1e9) >= args.last5_range)
        & (proto["pre_trade_count"].fillna(-1e9) >= args.pre_trade_count)
        & (proto["float_lt_20m"].fillna(False).astype(bool))
        & (proto["pre_range_pct_4_8"].fillna(-1e9) >= args.pre_vol_4_8)
    ]

    def compute_metrics(cand: pd.DataFrame):
        cand_per_day = cand.groupby("trade_date")["symbol"].nunique()
        avg_cand = cand_per_day.mean() if not cand_per_day.empty else 0.0
        recalls = []
        for d, top_set in gapper_sets.items():
            day_cand = set(cand[cand["trade_date"] == d]["symbol"])
            if not top_set:
                continue
            recalls.append(len(day_cand & top_set) / len(top_set))
        avg_recall = (sum(recalls) / len(recalls)) * 100.0 if recalls else 0.0
        return avg_cand, avg_recall

    old_avg_cand, old_avg_recall = compute_metrics(old_cand)
    proto_avg_cand, proto_avg_recall = compute_metrics(proto_cand)

    out_df = pd.DataFrame(
        [
            {"strategy": "old_pillars", "avg_candidates_per_day": old_avg_cand, "avg_recall_top5_pct": old_avg_recall},
            {"strategy": "prototype_prescreen", "avg_candidates_per_day": proto_avg_cand, "avg_recall_top5_pct": proto_avg_recall},
        ]
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.output, index=False)

    # Plot
    plt.figure()
    plt.scatter(out_df["avg_candidates_per_day"], out_df["avg_recall_top5_pct"])
    for _, row in out_df.iterrows():
        plt.text(row["avg_candidates_per_day"], row["avg_recall_top5_pct"], row["strategy"])
    plt.xlabel("Avg candidates/day")
    plt.ylabel("Avg recall on top5 gappers (%)")
    plt.title("Old Pillars vs Prototype Prescreen")
    plt.tight_layout()
    plot_path = Path(args.output).with_suffix(".png")
    plt.savefig(plot_path, dpi=150)

    print(args.output)
    print(plot_path)


if __name__ == "__main__":
    main()
