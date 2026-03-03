"""
analyze.py — Query and report on optimization results stored in SQLite.

Usage:
    python optimizer/analyze.py summary
    python optimizer/analyze.py top-runs --n 20
    python optimizer/analyze.py param-sensitivity --param a_min_relative_volume
    python optimizer/analyze.py trades --run-id optuna_00042
    python optimizer/analyze.py compare-defaults

All commands accept --db to point at a non-default DB file.
"""

from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import json
import sqlite3
from pathlib import Path

from optimizer.results_db import DEFAULT_DB_PATH


# ── DB helpers ────────────────────────────────────────────────────────────────

def _conn(db_path: str | None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not path.exists():
        print(f"ERROR: DB not found: {path}")
        sys.exit(1)
    return sqlite3.connect(str(path))


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_summary(conn: sqlite3.Connection) -> None:
    total_runs   = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    total_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    best  = conn.execute("SELECT run_id, objective, profit_factor, total_pnl FROM runs ORDER BY objective DESC LIMIT 1").fetchone()
    worst = conn.execute("SELECT run_id, objective, profit_factor, total_pnl FROM runs ORDER BY objective ASC  LIMIT 1").fetchone()
    avg   = conn.execute("SELECT AVG(objective), AVG(profit_factor), AVG(total_pnl) FROM runs").fetchone()

    print(f"\n{'='*55}")
    print(f"  Optimization Results Summary")
    print(f"{'='*55}")
    print(f"  Total runs   : {total_runs:,}")
    print(f"  Total trades : {total_trades:,}")
    if avg:
        print(f"  Avg objective: {avg[0]:.3f}")
        print(f"  Avg PF       : {avg[1]:.2f}")
        print(f"  Avg P&L      : ${avg[2]:+,.0f}")
    if best:
        print(f"\n  Best  run : {best[0]:<35} obj={best[1]:.3f}  PF={best[2]:.2f}  P&L=${best[3]:+,.0f}")
    if worst:
        print(f"  Worst run : {worst[0]:<35} obj={worst[1]:.3f}  PF={worst[2]:.2f}  P&L=${worst[3]:+,.0f}")
    print()


def cmd_top_runs(conn: sqlite3.Connection, n: int = 20) -> None:
    rows = conn.execute(
        """
        SELECT run_id, total_trades, win_rate, profit_factor, total_pnl, max_drawdown, objective
        FROM runs
        ORDER BY objective DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()

    print(f"\n{'Run ID':<38} {'Trades':>6} {'WR%':>6} {'PF':>6} {'P&L':>9} {'DD':>8} {'Obj':>7}")
    print('─' * 85)
    for run_id, trades, wr, pf, pnl, dd, obj in rows:
        print(f"{run_id:<38} {trades:>6} {wr:>5.1f}% {pf:>6.2f} ${pnl:>8,.0f} ${dd:>7,.0f} {obj:>7.3f}")


def cmd_param_sensitivity(conn: sqlite3.Connection, param_name: str) -> None:
    """Show how objective changes as one param varies (from sweep runs)."""
    rows = conn.execute(
        "SELECT params_json, objective, profit_factor, total_pnl, total_trades, win_rate FROM runs ORDER BY run_id"
    ).fetchall()

    values: list[tuple] = []
    for params_json, obj, pf, pnl, trades, wr in rows:
        params = json.loads(params_json)
        if param_name in params:
            values.append((params[param_name], obj, pf, pnl, trades, wr))

    if not values:
        # Try with prefix stripped
        stripped = param_name.lstrip('ab_c')
        for params_json, obj, pf, pnl, trades, wr in rows:
            params = json.loads(params_json)
            for k, v in params.items():
                if k.endswith(stripped):
                    values.append((v, obj, pf, pnl, trades, wr))
                    break

    if not values:
        print(f"No data found for param '{param_name}'.")
        print("Tip: use the full key like 'a_min_relative_volume' or 'c_target1_ratio'")
        return

    values.sort(key=lambda x: x[0])
    default_run = conn.execute(
        "SELECT params_json, objective FROM runs WHERE run_id LIKE 'sweep__%' ORDER BY created_at LIMIT 1"
    ).fetchone()

    print(f"\nSensitivity: {param_name}")
    print(f"{'Value':>14} {'Obj':>8} {'PF':>7} {'P&L':>9} {'Trades':>7} {'WR%':>6}")
    print('─' * 58)
    for val, obj, pf, pnl, trades, wr in values:
        marker = ' ◀ default' if abs(val - _get_default(param_name)) < 1e-9 else ''
        print(f"{val:>14} {obj:>8.3f} {pf:>7.2f} ${pnl:>8,.0f} {trades:>7} {wr:>5.1f}%{marker}")


def cmd_trades(conn: sqlite3.Connection, run_id: str) -> None:
    rows = conn.execute(
        """
        SELECT date, symbol, pattern, entry_price, exit_price, shares, pnl, exit_reason, hold_minutes
        FROM trades WHERE run_id = ?
        ORDER BY date, pnl DESC
        """,
        (run_id,),
    ).fetchall()

    if not rows:
        print(f"No trades found for run_id: {run_id}")
        return

    total = sum(r[6] for r in rows)
    winners = sum(1 for r in rows if r[6] > 0)
    print(f"\nTrades for {run_id}: {len(rows)} trades, {winners}W/{len(rows)-winners}L, total P&L ${total:+,.2f}\n")
    print(f"{'Date':>12} {'Sym':>6} {'Pattern':>15} {'Entry':>7} {'Exit':>7} {'Shr':>5} {'P&L':>8} {'Reason':>18} {'Min':>4}")
    print('─' * 95)
    for date, sym, pat, entry, exit_, shr, pnl, reason, mins in rows:
        print(f"{date:>12} {sym:>6} {pat:>15} ${entry:>6.2f} ${exit_:>6.2f} {shr:>5} ${pnl:>7.2f} {reason:>18} {mins:>4}")


def cmd_compare_defaults(conn: sqlite3.Connection) -> None:
    """Show the best run vs the default-param run (if it exists)."""
    default_run = conn.execute(
        "SELECT run_id, objective, profit_factor, total_pnl FROM runs WHERE run_id = 'defaults'"
    ).fetchone()
    best_run = conn.execute(
        "SELECT run_id, objective, profit_factor, total_pnl FROM runs ORDER BY objective DESC LIMIT 1"
    ).fetchone()

    print(f"\n{'='*55}")
    print("  Default vs Best")
    print(f"{'='*55}")
    if default_run:
        print(f"  Default : obj={default_run[1]:.3f}  PF={default_run[2]:.2f}  P&L=${default_run[3]:+,.0f}")
    else:
        print("  Default : (no 'defaults' run found — run sweep with defaults first)")
    if best_run:
        print(f"  Best    : {best_run[0]}  obj={best_run[1]:.3f}  PF={best_run[2]:.2f}  P&L=${best_run[3]:+,.0f}")
    print()


# ── Utility ───────────────────────────────────────────────────────────────────

def _get_default(param_name: str) -> float:
    """Return the default value for a flattened param key (best effort)."""
    from optimizer.run_config import RunConfig
    d = RunConfig.defaults().to_flat_dict()
    return float(d.get(param_name, 0))


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze optimization results')
    parser.add_argument('--db', default=None, help='SQLite DB path')
    sub = parser.add_subparsers(dest='cmd', required=True)

    sub.add_parser('summary',          help='High-level overview of all runs')
    top_p = sub.add_parser('top-runs', help='List top N runs by objective')
    top_p.add_argument('--n', type=int, default=20)

    sens_p = sub.add_parser('param-sensitivity', help='Sensitivity of one param (from sweep)')
    sens_p.add_argument('--param', required=True,
                        help='Flat param key e.g. a_min_relative_volume, c_target1_ratio')

    bt_p = sub.add_parser('trades', help='Per-trade detail for a run')
    bt_p.add_argument('--run-id', required=True)

    sub.add_parser('compare-defaults', help='Default config vs best found')

    args = parser.parse_args()
    conn = _conn(args.db)

    if args.cmd == 'summary':
        cmd_summary(conn)
    elif args.cmd == 'top-runs':
        cmd_top_runs(conn, args.n)
    elif args.cmd == 'param-sensitivity':
        cmd_param_sensitivity(conn, args.param)
    elif args.cmd == 'trades':
        cmd_trades(conn, args.run_id)
    elif args.cmd == 'compare-defaults':
        cmd_compare_defaults(conn)

    conn.close()
