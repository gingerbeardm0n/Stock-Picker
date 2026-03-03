#!/usr/bin/env python3
"""
Sweep day-gain and rel-vol thresholds against top gappers only.
Outputs pass rates for gappers (no non-gapper candidate counts).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description="Sweep thresholds on top gappers CSV")
    parser.add_argument("--input", required=True, help="Path to top_gappers CSV")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument(
        "--day-gain-thresholds",
        default="2,3,5,7,10",
        help="Comma-separated day gain thresholds (%)",
    )
    parser.add_argument(
        "--rel-vol-thresholds",
        default="1.5,2,3,5",
        help="Comma-separated rel vol thresholds (x)",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    df["trade_date"] = pd.to_datetime(df["trade_date"])

    day_thresholds = [float(x) for x in args.day_gain_thresholds.split(",")]
    rel_thresholds = [float(x) for x in args.rel_vol_thresholds.split(",")]

    output_path = args.output or str(Path(args.input).with_name("top_gappers_threshold_sweep.csv"))

    rows = []
    for day_t in day_thresholds:
        for rel_t in rel_thresholds:
            day_pass = df["day_gain_pct_929plus"].fillna(-1e9) >= day_t
            rel_pass = df["rel_vol_30d_929plus"].fillna(-1e9) >= rel_t
            float_pass = df["float_lt_20m"].fillna(False).astype(bool)

            all_pass = day_pass & rel_pass & float_pass

            # overall pass rates across all gappers
            pass_rate = all_pass.mean() * 100.0
            day_rate = day_pass.mean() * 100.0
            rel_rate = rel_pass.mean() * 100.0
            float_rate = float_pass.mean() * 100.0

            # per-day average pass (gappers only)
            by_day = df.groupby("trade_date").apply(
                lambda g: (
                    (g["day_gain_pct_929plus"].fillna(-1e9) >= day_t)
                    & (g["rel_vol_30d_929plus"].fillna(-1e9) >= rel_t)
                    & (g["float_lt_20m"].fillna(False).astype(bool))
                ).mean()
            )
            avg_daily_pass_rate = by_day.mean() * 100.0

            rows.append(
                {
                    "day_gain_threshold": day_t,
                    "rel_vol_threshold": rel_t,
                    "pass_rate_all_gappers_pct": pass_rate,
                    "pass_rate_day_gain_pct": day_rate,
                    "pass_rate_rel_vol_pct": rel_rate,
                    "pass_rate_float_pct": float_rate,
                    "avg_daily_pass_rate_pct": avg_daily_pass_rate,
                }
            )

    out_df = pd.DataFrame(rows).sort_values(
        ["pass_rate_all_gappers_pct", "avg_daily_pass_rate_pct"], ascending=False
    )
    out_df.to_csv(output_path, index=False)
    print(f"Wrote sweep results to {output_path}")


if __name__ == "__main__":
    main()
