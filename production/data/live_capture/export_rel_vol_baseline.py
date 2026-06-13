"""
export_rel_vol_baseline.py — export the live rel-vol denominator baseline.

The simulators compute relative volume as today's cumulative volume at 9:25 ET
(minute_of_day=565) ÷ the 30-day average cumulative volume at the same minute,
read from the `rel_vol_cum_cache` TimescaleDB table. The live runners run on
Render with NO database access, so the 30-day-average denominator must be
shipped to them.

This script queries `rel_vol_cum_cache` for AVG(cum_total) per symbol over the
last 30 calendar days at minute_of_day=565 and writes data/rel_vol_baseline.json:

    {"as_of": "YYYY-MM-DD", "minute_of_day": 565, "baselines": {"SYM": avg, ...}}

The live runner fetches that file from the dedicated `data` branch via raw
GitHub. See docs/REL_VOL_LIVE_PARITY_DESIGN.md.

Usage:
    python export_rel_vol_baseline.py            # write JSON only (default)
    python export_rel_vol_baseline.py --push     # also commit + force-push to
                                                 # the 'data' branch (never main)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date

import psycopg2
from dotenv import load_dotenv

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
load_dotenv(os.path.join(REPO_ROOT, '.env.paper'))

# Same DSN handling as pull_live_bars.py: require env, never hardcode the secret.
DB_DSN = os.getenv('DB_DSN') or os.getenv('OPTUNA_STORAGE')
if not DB_DSN:
    sys.exit("Set DB_DSN (postgresql://user:pass@host:5432/stockdata) in env or .env.paper")

MINUTE_OF_DAY = 565  # 9:25 ET — the minute the simulators use
OUTPUT_PATH = os.path.join(REPO_ROOT, 'data', 'rel_vol_baseline.json')
DATA_BRANCH = 'data'

QUERY = """
    SELECT symbol, AVG(cum_total) AS avg_cum
    FROM rel_vol_cum_cache
    WHERE trade_date >= (CURRENT_DATE - INTERVAL '30 days')
      AND minute_of_day = %s
    GROUP BY symbol
"""


def export() -> str:
    """Query the baseline and write data/rel_vol_baseline.json. Returns the path."""
    conn = psycopg2.connect(DB_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(QUERY, (MINUTE_OF_DAY,))
            rows = cur.fetchall()
    finally:
        conn.close()

    baselines = {sym: float(avg) for sym, avg in rows if avg is not None and float(avg) > 0}

    payload = {
        'as_of': date.today().isoformat(),
        'minute_of_day': MINUTE_OF_DAY,
        'baselines': baselines,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(payload, f, separators=(',', ':'))

    print(f"Wrote {OUTPUT_PATH}: {len(baselines):,} symbols, as_of={payload['as_of']}")
    return OUTPUT_PATH


def push_to_data_branch(json_path: str) -> None:
    """Commit the baseline file to the dedicated 'data' branch and force-push it,
    WITHOUT touching the user's working tree or main.

    Uses a throwaway temp worktree + an orphan branch so history is irrelevant
    (single-file branch) and no branch is ever checked out in the main tree.
    """
    rel_path = os.path.relpath(json_path, REPO_ROOT).replace(os.sep, '/')

    def git(*args: str, cwd: str = REPO_ROOT) -> str:
        return subprocess.run(
            ['git', *args], cwd=cwd, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    with tempfile.TemporaryDirectory() as tmp:
        wt = os.path.join(tmp, 'data_wt')
        # Detached worktree so we never check the data branch out in the main tree.
        git('worktree', 'add', '--detach', wt)
        try:
            # Fresh orphan branch — single-file, history irrelevant.
            git('checkout', '--orphan', DATA_BRANCH, cwd=wt)
            git('reset', cwd=wt)
            os.makedirs(os.path.join(wt, os.path.dirname(rel_path)), exist_ok=True)
            with open(json_path) as src, open(os.path.join(wt, rel_path), 'w') as dst:
                dst.write(src.read())
            git('add', rel_path, cwd=wt)
            git('commit', '-m', f'data: rel_vol baseline {date.today().isoformat()}', cwd=wt)
            git('push', '--force', 'origin', f'{DATA_BRANCH}:{DATA_BRANCH}', cwd=wt)
            print(f"Force-pushed {rel_path} to origin/{DATA_BRANCH}")
        finally:
            git('worktree', 'remove', '--force', wt)


def main() -> None:
    ap = argparse.ArgumentParser(description='Export the live rel-vol baseline.')
    ap.add_argument('--push', action='store_true',
                    help="Commit + force-push to the 'data' branch (never main).")
    args = ap.parse_args()

    json_path = export()
    if args.push:
        push_to_data_branch(json_path)
    else:
        print("(no --push: file written locally only)")


if __name__ == '__main__':
    main()
