#!/usr/bin/env python3
"""
Create Pillar 2+3 Universe
==========================
Filters gapper_universe.csv to stocks that genuinely passed Ross Cameron's
Pillars 2 and 3 as of premarket each morning:

  Pillar 2: Still up 10%+ at EITHER the 9:25am OR the 9:30am snapshot
            (qualified_when in HELD_BOTH, HELD_925_ONLY, HELD_930_ONLY)
            → excludes HIT_ONLY (touched 10% but faded before either snapshot)

  Pillar 3: Relative volume >= 5x vs. 30-day average of same PM window
            (pillar3_pass == True)

Output: analysis/pillar23_universe.csv
Format: date,symbol  (two-column, detected as "date-specific" by optuna_run.py)

Usage:
  python analysis/create_pillar23_universe.py
"""

import csv
import os

INPUT  = os.path.join(os.path.dirname(__file__), 'gapper_universe.csv')
OUTPUT = os.path.join(os.path.dirname(__file__), 'pillar23_universe.csv')

HELD_QUALIFIERS = {'HELD_BOTH', 'HELD_925_ONLY', 'HELD_930_ONLY'}


def main():
    print("=" * 60)
    print("  CREATE PILLAR 2+3 UNIVERSE")
    print("=" * 60)

    if not os.path.exists(INPUT):
        print(f"ERROR: {INPUT} not found.")
        print("Run analysis/build_gapper_universe.py first.")
        return

    rows_read    = 0
    rows_written = 0
    skipped_hit_only  = 0
    skipped_no_relvol = 0

    by_date = {}

    with open(INPUT, newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_read += 1
            qualified_when = row.get('qualified_when', '').strip()
            pillar3_pass   = row.get('pillar3_pass', '').strip()

            # Pillar 2: must still be holding 10%+ at a snapshot time
            if qualified_when not in HELD_QUALIFIERS:
                skipped_hit_only += 1
                continue

            # Pillar 3: must have 5x+ relative volume
            if pillar3_pass.lower() != 'true':
                skipped_no_relvol += 1
                continue

            date_str = row['date'].strip()
            symbol   = row['symbol'].strip()
            by_date.setdefault(date_str, []).append(symbol)
            rows_written += 1

    # Write output
    with open(OUTPUT, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'symbol'])
        for date_str in sorted(by_date.keys()):
            for symbol in sorted(by_date[date_str]):
                writer.writerow([date_str, symbol])

    print(f"\n  Input rows read:          {rows_read:,}")
    print(f"  Skipped (HIT_ONLY):       {skipped_hit_only:,}  (faded below 10% before open)")
    print(f"  Skipped (no rel vol):     {skipped_no_relvol:,}  (pillar 3 failed)")
    print(f"  Qualifying rows written:  {rows_written:,}")
    print(f"  Dates covered:            {len(by_date)}")
    if by_date:
        avg = rows_written / len(by_date)
        print(f"  Avg stocks/day:           {avg:.1f}")
        dates = sorted(by_date.keys())
        print(f"  Date range:               {dates[0]} to {dates[-1]}")

    print(f"\n  Output: {OUTPUT}")
    print("\n  Sample (first 10 rows):")
    with open(OUTPUT) as f:
        for i, line in enumerate(f):
            if i > 10:
                break
            print(f"    {line.rstrip()}")


if __name__ == '__main__':
    main()
