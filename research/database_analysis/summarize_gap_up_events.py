#!/usr/bin/env python3
"""
Summarize gap-up events CSV and generate aggregated plots.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize gap-up events CSV")
    parser.add_argument("--input", required=True, help="Path to gap_up_events CSV")
    parser.add_argument("--output-dir", default="database/audit_reports", help="Output dir")
    parser.add_argument("--day-gain-threshold", type=float, default=10.0, help="Day gain threshold (%)")
    parser.add_argument("--rel-vol-threshold", type=float, default=5.0, help="Rel vol threshold (x)")
    parser.add_argument(
        "--weight-col",
        default="day_gain_pct_event",
        help="Column to use for weighted averages",
    )
    parser.add_argument(
        "--weight-mode",
        choices=["raw", "log1p"],
        default="raw",
        help="Weighting mode: raw or log1p",
    )
    args = parser.parse_args()

    csv_path = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(csv_path)

    summary = []
    summary.append(f"rows={len(df)}")
    summary.append(f"unique_symbols={df['symbol'].nunique()}")
    summary.append("event_type_counts:\n" + df["event_type"].value_counts().to_string())

    for col in [
        "rel_vol_30d",
        "day_gain_pct_929plus",
        "day_gain_pct_event",
        "float_shares",
        "pillar_day_gain_10pct",
        "pillar_rel_vol_5x",
        "pillar_score",
    ]:
        if col in df.columns:
            pct = df[col].notna().mean() * 100
            summary.append(f"{col}_non_null_pct={pct:.1f}%")

    # Recompute pillars with requested thresholds (CSV-only)
    df["pillar_day_gain_custom"] = (
        df["day_gain_pct_929plus"].fillna(-1e9) >= args.day_gain_threshold
    )
    df["pillar_rel_vol_custom"] = df["rel_vol_30d"].fillna(-1e9) >= args.rel_vol_threshold
    df["pillar_float_custom"] = df["float_lt_20m"].fillna(False).astype(bool)
    df["pillar_score_custom"] = (
        df["pillar_day_gain_custom"].astype(int)
        + df["pillar_rel_vol_custom"].astype(int)
        + df["pillar_float_custom"].astype(int)
    )

    # Pillar true rates (custom thresholds)
    pillar_cols = ["pillar_day_gain_custom", "pillar_rel_vol_custom", "pillar_float_custom"]
    pillar_rates = {}
    for col in pillar_cols:
        if col in df.columns:
            pillar_rates[col] = df[col].fillna(False).mean() * 100

    summary_path = out_dir / (csv_path.stem + "_summary.txt")
    summary_path.write_text("\n\n".join(summary))

    # Bar chart: pillar true rates
    if pillar_rates:
        plt.figure()
        labels = list(pillar_rates.keys())
        values = [pillar_rates[k] for k in labels]
        plt.bar(labels, values)
        plt.title("Pillar True Rate (%)")
        plt.ylabel("Percent of events")
        plt.xticks(rotation=20, ha="right")
        plt.tight_layout()
        plt.savefig(out_dir / (csv_path.stem + "_pillar_rates.png"), dpi=150)
        plt.close()

    # Histogram: pillar score (custom)
    if "pillar_score_custom" in df.columns:
        plt.figure()
        df["pillar_score_custom"].dropna().hist(bins=range(0, 5))
        plt.title("Pillar Score Distribution")
        plt.xlabel("pillar_score")
        plt.ylabel("count")
        plt.tight_layout()
        plt.savefig(out_dir / (csv_path.stem + "_pillar_score.png"), dpi=150)
        plt.close()

    # Unweighted averages for pillar values
    unweighted_rel_vol = df["rel_vol_30d"].mean(skipna=True)
    unweighted_day_gain = df["day_gain_pct_929plus"].mean(skipna=True)
    unweighted_float = df["pillar_float_custom"].mean(skipna=True)
    summary.append(f"unweighted_avg_rel_vol_30d={unweighted_rel_vol:.3f}")
    summary.append(f"unweighted_avg_day_gain_pct_929plus={unweighted_day_gain:.3f}")
    summary.append(f"unweighted_frac_float_lt_20m={unweighted_float:.3f}")

    # Weighted averages
    weight_col = args.weight_col
    if weight_col in df.columns:
        weights = df[weight_col].fillna(0).clip(lower=0)
        if args.weight_mode == "log1p":
            weights = (weights + 1.0).apply(lambda x: __import__("math").log(x))
        wsum = weights.sum()
        if wsum > 0:
            w_rel_vol = (df["rel_vol_30d"].fillna(0) * weights).sum() / wsum
            w_day_gain = (df["day_gain_pct_929plus"].fillna(0) * weights).sum() / wsum
            w_float = (df["pillar_float_custom"].astype(int) * weights).sum() / wsum
            summary.append(f"weighted_by={weight_col}")
            summary.append(f"weight_mode={args.weight_mode}")
            summary.append(f"weighted_avg_rel_vol_30d={w_rel_vol:.3f}")
            summary.append(f"weighted_avg_day_gain_pct_929plus={w_day_gain:.3f}")
            summary.append(f"weighted_frac_float_lt_20m={w_float:.3f}")
            summary_path.write_text("\n\n".join(summary))

    print(f"summary={summary_path}")
    print(f"plots={csv_path.stem}_pillar_rates.png, {csv_path.stem}_pillar_score.png")


if __name__ == "__main__":
    main()
