#!/usr/bin/env python3
"""
Build merged "true top gappers" CSVs from monthly top-100 gap-run files.

Algorithm per month:
  1. Take the top 50 from the "by count" list and top 50 from the
     "by max gain" list.
  2. Add them to the result in that order, skipping duplicates.
  3. Continue from rank 51 onward, alternating one symbol from each list
     and skipping duplicates until the result reaches 100 symbols or both
     lists are exhausted.
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Iterable


def read_symbols(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [row["symbol"].strip() for row in reader if row.get("symbol")]


def add_unique(target: list[str], seen: set[str], symbols: Iterable[str]) -> None:
    for symbol in symbols:
        if symbol in seen:
            continue
        target.append(symbol)
        seen.add(symbol)


def build_true_top_list(by_count: list[str], by_max: list[str], target_size: int = 100) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    add_unique(result, seen, by_count[:50])
    add_unique(result, seen, by_max[:50])

    for idx in range(50, max(len(by_count), len(by_max))):
        if len(result) >= target_size:
            break
        if idx < len(by_count):
            add_unique(result, seen, [by_count[idx]])
        if len(result) >= target_size:
            break
        if idx < len(by_max):
            add_unique(result, seen, [by_max[idx]])

    return result[:target_size]


def find_month_pairs(base_dir: Path) -> list[tuple[str, Path, Path]]:
    count_files = sorted(base_dir.glob("top_100_gaprun_symbols_by_count_*.csv"))
    pairs: list[tuple[str, Path, Path]] = []
    for count_path in count_files:
        month = count_path.stem.replace("top_100_gaprun_symbols_by_count_", "")
        max_path = base_dir / f"top_100_gaprun_symbols_by_max_gain_{month}.csv"
        if max_path.exists():
            pairs.append((month, count_path, max_path))
    return pairs


def write_output(output_dir: Path, month: str, symbols: list[str]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"true_top_gappers_{month}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol"])
        for symbol in symbols:
            writer.writerow([symbol])
    return csv_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate monthly true top gapper lists")
    parser.add_argument(
        "--base-dir",
        default="database/audit_reports/monthly_gaprun_lists",
        help="Directory containing monthly top-100 gaprun CSVs",
    )
    parser.add_argument("--month", help="Single month to generate, format YYYY-MM")
    parser.add_argument(
        "--output-dir",
        default="database/audit_reports/monthly_gaprun_lists/true_gappers_by_month",
        help="Directory to write merged monthly CSVs",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    output_dir = Path(args.output_dir)
    pairs = find_month_pairs(base_dir)
    if args.month:
        pairs = [pair for pair in pairs if pair[0] == args.month]

    if not pairs:
        raise SystemExit("No matching monthly top-gapper file pairs found.")

    manifest_rows: list[dict[str, object]] = []
    for month, count_path, max_path in pairs:
        by_count = read_symbols(count_path)
        by_max = read_symbols(max_path)
        merged = build_true_top_list(by_count, by_max, target_size=100)
        csv_path = write_output(output_dir, month, merged)

        manifest_rows.append(
            {
                "month": month,
                "merged_count": len(merged),
                "csv_path": str(csv_path),
            }
        )
        print(f"{month}: wrote {csv_path}")

    manifest_path = output_dir / "true_top_gappers_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["month", "merged_count", "csv_path"])
        writer.writeheader()
        writer.writerows(manifest_rows)
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
