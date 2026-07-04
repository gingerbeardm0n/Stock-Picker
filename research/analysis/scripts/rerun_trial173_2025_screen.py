"""One-off: re-measure trial-173 (VWAP + Scalp) over full 2025 under the new
screen_candidates() semantics (commit 446b27d). Run-and-report only; no source edits.

Outputs aggregate metrics + per-day trade rows for both strategies as JSON to stdout.
"""
import sys, os, json, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))

logging.disable(logging.WARNING)

from trading.live_vwap_runner import TRIAL_173_CONFIG as VWAP_CFG
from trading.live_scalp_runner import TRIAL_173_CONFIG as SCALP_CFG
from simulator.vwap_simulation import run_vwap_date_range
from simulator.scalp_simulation import run_scalp_date_range

START, END = '2025-01-01', '2025-12-31'
ACCT = 5000.0


def summarize(name, r):
    print(f"\n===== {name} =====", flush=True)
    print(f"trades={r['total_trades']} WR={r['win_rate']:.1f}% "
          f"pnl=${r['total_pnl']:+,.2f} avg/day=${r['avg_daily_pnl']:+.2f} "
          f"maxDD=${r['max_drawdown']:.2f} PF={r['profit_factor']:.2f} "
          f"days_traded={r['days_traded']}", flush=True)
    rows = []
    for t in r['trades']:
        rows.append({
            'date': str(t.date), 'symbol': t.symbol, 'pnl': round(t.pnl, 2),
            'entry': round(t.entry_price, 4), 'exit': round(t.exit_price, 4),
            'shares': t.shares, 'entry_time': str(t.entry_time),
            'exit_type': t.exit_type, 'gap_pct': round(t.gap_pct, 2),
        })
    return {
        'total_trades': r['total_trades'], 'win_rate': round(r['win_rate'], 2),
        'total_pnl': round(r['total_pnl'], 2), 'avg_daily_pnl': r['avg_daily_pnl'],
        'max_drawdown': r['max_drawdown'], 'profit_factor': r['profit_factor'],
        'days_traded': r['days_traded'], 'winners': r['winners'], 'losers': r['losers'],
        'trades': rows,
    }


print("Running VWAP trial-173 over 2025...", flush=True)
vwap = run_vwap_date_range(VWAP_CFG, START, END, account_size=ACCT, verbose=False)
vwap_out = summarize('VWAP RECLAIM (trial 173)', vwap)

print("\nRunning SCALP trial-173 over 2025...", flush=True)
scalp = run_scalp_date_range(SCALP_CFG, START, END, account_size=ACCT, verbose=False)
scalp_out = summarize('OPENING BELL SCALP (trial 173)', scalp)

out_path = os.path.join(os.path.dirname(__file__), '..', 'outputs', 'trial173_2025_screen_rerun.json')
out_path = os.path.abspath(out_path)
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, 'w') as f:
    json.dump({'vwap': vwap_out, 'scalp': scalp_out}, f, indent=2)
print(f"\nWROTE {out_path}", flush=True)
