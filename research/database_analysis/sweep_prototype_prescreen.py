#!/usr/bin/env python3
"""
Sweep prototype prescreen thresholds to optimize recall on top gappers.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep prototype prescreen thresholds")
    parser.add_argument("--prototype", required=True, help="Prototype prescreen CSV")
    parser.add_argument("--top-gappers", required=True, help="Top gappers CSV")
    parser.add_argument("--output", default="database/audit_reports/prototype_sweep.csv")
    parser.add_argument("--pre-range-thresholds", default="1,2,3,4,5")
    parser.add_argument("--last5-range-thresholds", default="0.5,1,1.5,2,3")
    parser.add_argument("--pre-trade-count-thresholds", default="10,25,50,100,200")
    args = parser.parse_args()

    proto = pd.read_csv(args.prototype)
    gappers = pd.read_csv(args.top_gappers)
    gappers["trade_date"] = pd.to_datetime(gappers["trade_date"]).dt.date
    proto["trade_date"] = pd.to_datetime(proto["trade_date"]).dt.date

    gapper_sets = gappers.groupby("trade_date")["symbol"].apply(set).to_dict()

    pre_ranges = [float(x) for x in args.pre_range_thresholds.split(",")]
    last5_ranges = [float(x) for x in args.last5_range_thresholds.split(",")]
    trade_counts = [float(x) for x in args.pre_trade_count_thresholds.split(",")]

    rows = []
    for pre_r in pre_ranges:
        for last5_r in last5_ranges:
            for tc in trade_counts:
                cand = proto[
                    (proto["pre_range_pct_4_8"].fillna(-1e9) >= pre_r)
                    & (proto["last5_range_pct"].fillna(-1e9) >= last5_r)
                    & (proto["pre_trade_count"].fillna(-1e9) >= tc)
                    & (proto["float_lt_20m"].fillna(False).astype(bool))
                ]

                cand_per_day = cand.groupby("trade_date")["symbol"].nunique()
                avg_cand = cand_per_day.mean() if not cand_per_day.empty else 0.0

                recalls = []
                for d, top_set in gapper_sets.items():
                    day_cand = set(cand[cand["trade_date"] == d]["symbol"])
                    if not top_set:
                        continue
                    recalls.append(len(day_cand & top_set) / len(top_set))
                avg_recall = (sum(recalls) / len(recalls)) * 100.0 if recalls else 0.0

                rows.append(
                    {
                        "pre_range_pct_4_8": pre_r,
                        "last5_range_pct": last5_r,
                        "pre_trade_count": tc,
                        "avg_candidates_per_day": avg_cand,
                        "avg_recall_top5_pct": avg_recall,
                    }
                )

    out_df = pd.DataFrame(rows).sort_values(
        ["avg_recall_top5_pct", "avg_candidates_per_day"], ascending=False
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(args.output, index=False)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
