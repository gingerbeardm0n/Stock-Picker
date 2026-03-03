#!/usr/bin/env python3
"""
Analyze gap-run feature dataset:
  1) Feature correlations with run_gain_pct
  2) Simple linear regression feature importance (standardized)
  3) K-means clustering on features to find common pre-run patterns
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd


FEATURE_COLS = [
    "pre_range_pct",
    "pre_body_pct",
    "pre_volume",
    "pre_trade_count",
    "pre_rel_vol_30d",
    "pre_return_pct",
    "pre_range_total_pct",
    "pre_volume_sum",
    "pre_green_frac",
    "last5_return_pct",
    "last5_volume_sum",
    "last5_green_frac",
    "last5_range_pct",
    "pre_vol_4_8",
    "pre_trend_pct",
    "pre_range_pct_4_8",
]


def log_safe(series: pd.Series) -> pd.Series:
    return np.log1p(series.clip(lower=0))


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean()
    sigma = df.std(ddof=0).replace(0, 1)
    return (df - mu) / sigma


def kmeans(X: np.ndarray, k: int, max_iter: int = 100, seed: int = 7):
    rng = np.random.default_rng(seed)
    n = X.shape[0]
    idx = rng.choice(n, size=k, replace=False)
    centers = X[idx]
    labels = np.zeros(n, dtype=int)
    for _ in range(max_iter):
        # assign
        dists = np.linalg.norm(X[:, None, :] - centers[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
        # update
        for j in range(k):
            mask = labels == j
            if mask.any():
                centers[j] = X[mask].mean(axis=0)
    return labels, centers


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze gap-run feature patterns")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to gap_run_features CSV",
    )
    parser.add_argument("--k", type=int, default=5, help="Number of clusters")
    parser.add_argument(
        "--output-dir",
        default="database/audit_reports",
        help="Output directory",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prepare features
    feat = df[FEATURE_COLS].copy()

    # Log-transform heavy-tailed columns
    for col in ["pre_volume", "pre_trade_count", "pre_rel_vol_30d", "pre_volume_sum", "last5_volume_sum", "pre_vol_4_8"]:
        if col in feat.columns:
            feat[col] = log_safe(feat[col].fillna(0))

    # Fill remaining NaNs with median
    feat = feat.apply(lambda s: s.fillna(s.median()), axis=0)

    # Correlations (Spearman + Pearson)
    corr_pearson = feat.join(df["run_gain_pct"]).corr(numeric_only=True)["run_gain_pct"].drop("run_gain_pct")
    corr_spearman = feat.join(df["run_gain_pct"]).corr(method="spearman", numeric_only=True)["run_gain_pct"].drop("run_gain_pct")
    corr_df = pd.DataFrame({
        "feature": corr_pearson.index,
        "pearson_corr": corr_pearson.values,
        "spearman_corr": corr_spearman.values,
    }).sort_values("spearman_corr", key=lambda s: s.abs(), ascending=False)
    corr_df.to_csv(out_dir / "gap_run_feature_correlations.csv", index=False)

    # Linear regression feature importance (standardized)
    X = standardize(feat).values
    y = df["run_gain_pct"].values
    # add intercept
    X_design = np.c_[np.ones(len(X)), X]
    # least squares
    coef, *_ = np.linalg.lstsq(X_design, y, rcond=None)
    coef_df = pd.DataFrame({
        "feature": ["intercept"] + list(feat.columns),
        "coef": coef,
        "abs_coef": np.abs(coef),
    }).sort_values("abs_coef", ascending=False)
    coef_df.to_csv(out_dir / "gap_run_feature_importance.csv", index=False)

    # K-means clustering
    labels, centers = kmeans(X, k=args.k, max_iter=100, seed=7)
    df["cluster"] = labels
    cluster_summary = (
        df.groupby("cluster")
        .agg(
            count=("run_gain_pct", "size"),
            run_gain_mean=("run_gain_pct", "mean"),
            run_gain_median=("run_gain_pct", "median"),
            run_minutes_mean=("run_minutes", "mean"),
        )
        .reset_index()
        .sort_values("run_gain_mean", ascending=False)
    )
    cluster_summary.to_csv(out_dir / "gap_run_cluster_summary.csv", index=False)

    centers_df = pd.DataFrame(centers, columns=feat.columns)
    centers_df["cluster"] = np.arange(args.k)
    centers_df.to_csv(out_dir / "gap_run_cluster_centers.csv", index=False)

    print("wrote:")
    print(out_dir / "gap_run_feature_correlations.csv")
    print(out_dir / "gap_run_feature_importance.csv")
    print(out_dir / "gap_run_cluster_summary.csv")
    print(out_dir / "gap_run_cluster_centers.csv")


if __name__ == "__main__":
    main()
