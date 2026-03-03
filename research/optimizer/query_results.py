"""
query_results.py — Query optimizer results database for top-N trials or per-trade detail.

Usage:
    python optimizer/query_results.py                          # top 20 trials
    python optimizer/query_results.py --top 10                 # top 10 trials
    python optimizer/query_results.py --top 50 --csv           # top 50, write to CSV
    python optimizer/query_results.py --trade-detail 00492     # all trades for trial 492
    python optimizer/query_results.py --trade-detail 00492 --csv  # same, write to CSV
    python optimizer/query_results.py --db optimizer/meta_results.db --top 20
"""

import argparse
import csv as csv_module
import json
import os
import sqlite3
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def infer_b_indicators(p: dict) -> str:
    patterns = [name for name in ['bull_flag', 'micro_pullback', 'abcd', 'dip_buy', 'flat_top']
                if p.get(f'b_enable_{name}', False)]
    return '+'.join(patterns) if patterns else 'none'


def infer_exit_style(p: dict) -> str:
    td = p.get('c_trailing_stop_distance', 0)
    return f'trail({td:.3f})' if td and td > 0.01 else 'fixed_target'


def _open_db(db_path: str) -> sqlite3.Connection:
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)
    return sqlite3.connect(db_path)


# ── Top-N trials report ───────────────────────────────────────────────────────

def run_query(db_path: str, top_n: int, write_csv: bool = False) -> None:
    conn = _open_db(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT run_id, total_trades, winners, win_rate, profit_factor,
               total_pnl, max_drawdown, objective, params_json
        FROM runs
        WHERE total_trades > 0
        ORDER BY objective DESC
        LIMIT ?
    ''', (top_n,))
    rows = cursor.fetchall()

    cursor.execute('SELECT COUNT(*) FROM runs')
    total = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM runs WHERE total_trades > 0')
    with_trades = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM runs WHERE total_trades = 0')
    pruned = cursor.fetchone()[0]
    conn.close()

    if not rows:
        print("No results found in database.")
        return

    # Build display rows
    display = []
    for rank, row in enumerate(rows, 1):
        run_id, trades, winners, win_rate, pf, pnl, maxdd, obj, params_json = row
        p = json.loads(params_json) if params_json else {}
        display.append({
            'rank':     rank,
            'trial':    run_id.replace('optuna_', '').replace('meta_', 'm'),
            'pnl':      pnl,
            'trades':   trades,
            'win_rate': win_rate,
            'pf':       pf,
            'maxdd':    maxdd,
            'patterns': infer_b_indicators(p),
            'exit':     infer_exit_style(p),
            'rr':       p.get('b_min_rr_ratio', 0),
            'stop':     p.get('b_stop_buffer', 0),
            't1_ratio': p.get('c_target1_ratio', 0),
            't1_qty':   p.get('c_target1_qty_pct', 0),
        })

    # Terminal output
    print()
    print('=' * 155)
    print(f'  TOP {top_n} TRIALS  |  {db_path}')
    print(f'  Total runs: {total}  |  With trades: {with_trades}  |  Pruned (zero trades): {pruned}')
    print('=' * 155)
    print(f'{"Rank":<5} {"Trial":<10} {"P&L":>8}  {"Trades":>6} {"Win%":>6} {"PF":>6}  {"MaxDD":>8}  {"Patterns":<35} {"Exit":<18}  Key Params')
    print('-' * 155)
    for d in display:
        key = f'RR={d["rr"]:.2f} stop={d["stop"]:.3f} T1={d["t1_ratio"]:.2f}@{d["t1_qty"]:.0%}'
        print(f'{d["rank"]:<5} {d["trial"]:<10} ${d["pnl"]:>7,.0f}  {d["trades"]:>6} '
              f'{d["win_rate"]:>5.1f}% {d["pf"]:>6.2f}  ${d["maxdd"]:>7,.0f}  '
              f'{d["patterns"]:<35} {d["exit"]:<18}  {key}')
    print()
    best = display[0]
    print(f'  Best: ${best["pnl"]:,.0f} P&L  |  {best["trades"]} trades  |  '
          f'{best["win_rate"]:.1f}% win rate  |  {best["pf"]:.2f} profit factor')
    print()

    # CSV output
    if write_csv:
        csv_path = f'optimizer/top_{top_n}_trials.csv'
        with open(csv_path, 'w', newline='') as f:
            writer = csv_module.DictWriter(f, fieldnames=display[0].keys())
            writer.writeheader()
            writer.writerows(display)
        print(f'  CSV written: {csv_path}')
        print()


# ── Per-trade detail report ───────────────────────────────────────────────────

def run_trade_detail(db_path: str, trial_id: str, write_csv: bool = False) -> None:
    # Normalise: accept '492', '00492', 'optuna_00492' all the same
    trial_id = trial_id.strip()
    if not trial_id.startswith('optuna_') and not trial_id.startswith('meta_'):
        # Try zero-padded numeric form
        try:
            run_id = f'optuna_{int(trial_id):05d}'
        except ValueError:
            run_id = trial_id
    else:
        run_id = trial_id

    conn = _open_db(db_path)
    cursor = conn.cursor()

    # Fetch run summary
    cursor.execute('''
        SELECT total_trades, winners, win_rate, profit_factor, total_pnl,
               max_drawdown, params_json
        FROM runs WHERE run_id = ?
    ''', (run_id,))
    run_row = cursor.fetchone()
    if not run_row:
        print(f"ERROR: Trial '{run_id}' not found in {db_path}")
        conn.close()
        sys.exit(1)

    total_trades, winners, win_rate, pf, total_pnl, maxdd, params_json = run_row
    p = json.loads(params_json) if params_json else {}

    # Fetch individual trades
    cursor.execute('''
        SELECT date, symbol, pattern, entry_price, exit_price, shares,
               pnl, exit_reason, hold_minutes
        FROM trades
        WHERE run_id = ?
        ORDER BY ABS(pnl) DESC
    ''', (run_id,))
    trades = cursor.fetchall()
    conn.close()

    if not trades:
        print(f"No trades found for trial {run_id}.")
        return

    # Build display rows
    display = []
    for i, t in enumerate(trades, 1):
        date, symbol, pattern, entry, exit_price, shares, pnl, exit_reason, hold_min = t
        display.append({
            '#':            i,
            'date':         date,
            'symbol':       symbol,
            'pattern':      pattern,
            'entry':        entry,
            'exit':         exit_price,
            'shares':       shares,
            'pnl':          pnl,
            'exit_reason':  exit_reason,
            'hold_min':     hold_min,
            'result':       'WIN' if pnl > 0 else 'LOSS',
        })

    # Terminal output
    print()
    print('=' * 115)
    print(f'  TRADE DETAIL  |  Trial {run_id}  |  {db_path}')
    print(f'  Summary: ${total_pnl:,.0f} P&L  |  {total_trades} trades  |  '
          f'{win_rate:.1f}% win rate  |  {pf:.2f} PF  |  ${maxdd:,.0f} max drawdown')
    print(f'  Config:  {infer_b_indicators(p)}  |  {infer_exit_style(p)}  |  '
          f'RR={p.get("b_min_rr_ratio",0):.2f}  stop={p.get("b_stop_buffer",0):.3f}  '
          f'T1={p.get("c_target1_ratio",0):.2f}@{p.get("c_target1_qty_pct",0):.0%}')
    print('=' * 115)
    print(f'{"#":<4} {"Date":<12} {"Symbol":<8} {"Pattern":<16} {"Entry":>7} {"Exit":>7} '
          f'{"Shares":>6} {"P&L":>8} {"Exit Reason":<20} {"Hold":>5}  Result')
    print('-' * 115)

    for d in display:
        pnl_str = f'${d["pnl"]:+,.2f}'
        print(f'{d["#"]:<4} {d["date"]:<12} {d["symbol"]:<8} {d["pattern"]:<16} '
              f'${d["entry"]:>6.2f} ${d["exit"]:>6.2f} {d["shares"]:>6} '
              f'{pnl_str:>8} {d["exit_reason"]:<20} {d["hold_min"]:>4}m  '
              f'{d["result"]}')

    print()
    winners_list = [d['pnl'] for d in display if d['pnl'] > 0]
    losers_list  = [d['pnl'] for d in display if d['pnl'] <= 0]
    avg_win  = sum(winners_list) / len(winners_list) if winners_list else 0
    avg_loss = sum(losers_list)  / len(losers_list)  if losers_list  else 0
    avg_hold = sum(d['hold_min'] for d in display) / len(display)
    total_pnl_check = sum(d['pnl'] for d in display)
    print(f'  Avg win: ${avg_win:,.2f}  |  Avg loss: ${avg_loss:,.2f}  |  '
          f'Avg hold: {avg_hold:.0f} min  |  Total P&L: ${total_pnl_check:+,.2f}')
    print()

    # CSV output
    if write_csv:
        csv_path = f'optimizer/trade_detail_{run_id}.csv'
        with open(csv_path, 'w', newline='') as f:
            writer = csv_module.DictWriter(f, fieldnames=display[0].keys())
            writer.writeheader()
            writer.writerows(display)
        print(f'  CSV written: {csv_path}')
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Query optimizer results database')
    parser.add_argument('--top',          type=int, default=20,
                        help='Number of top trials to show (default: 20)')
    parser.add_argument('--trade-detail', metavar='TRIAL_ID', default=None,
                        help='Show all trades for a specific trial (e.g. 00492 or 492)')
    parser.add_argument('--csv',          action='store_true',
                        help='Write output to a CSV file in optimizer/')
    parser.add_argument('--db',           default='optimizer/results.db',
                        help='Path to results database (default: optimizer/results.db)')
    args = parser.parse_args()

    if args.trade_detail:
        run_trade_detail(args.db, args.trade_detail, write_csv=args.csv)
    else:
        run_query(args.db, args.top, write_csv=args.csv)
