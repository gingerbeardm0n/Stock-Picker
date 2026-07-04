"""Compare VWAP trial-173 over 2025 WITH vs WITHOUT screen_candidates().
Monkeypatches the screen to a no-op to reproduce pre-446b27d behavior, then
diffs per-day traded symbol / pnl. Run-and-report only.
"""
import sys, os, json, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'production')))
logging.disable(logging.WARNING)

START, END = '2025-01-01', '2025-12-31'
ACCT = 5000.0

from trading.live_vwap_runner import TRIAL_173_CONFIG as VWAP_CFG
import simulator.vwap_simulation as vsim


def per_day_map(r):
    m = {}
    for t in r['trades']:
        m[str(t.date)] = {'symbol': t.symbol, 'pnl': round(t.pnl, 2),
                          'gap_pct': round(t.gap_pct, 2), 'wr_win': t.pnl > 0}
    return m


# --- WITH screen (current/new semantics) ---
r_new = vsim.run_vwap_date_range(VWAP_CFG, START, END, account_size=ACCT, verbose=False)
new_map = per_day_map(r_new)

# --- WITHOUT screen (old semantics): patch screen_candidates to identity ---
_orig = vsim.screen_candidates
vsim.screen_candidates = lambda c: c
r_old = vsim.run_vwap_date_range(VWAP_CFG, START, END, account_size=ACCT, verbose=False)
vsim.screen_candidates = _orig
old_map = per_day_map(r_old)

print("OLD (no screen):", f"trades={r_old['total_trades']} WR={r_old['win_rate']:.1f}% "
      f"pnl=${r_old['total_pnl']:+,.2f} PF={r_old['profit_factor']:.2f} maxDD=${r_old['max_drawdown']:.2f}")
print("NEW (screen)   :", f"trades={r_new['total_trades']} WR={r_new['win_rate']:.1f}% "
      f"pnl=${r_new['total_pnl']:+,.2f} PF={r_new['profit_factor']:.2f} maxDD=${r_new['max_drawdown']:.2f}")

all_dates = sorted(set(old_map) | set(new_map))
changed = []
for d in all_dates:
    o = old_map.get(d)
    n = new_map.get(d)
    if o == n:
        continue
    if o and n and o['symbol'] == n['symbol'] and abs(o['pnl'] - n['pnl']) < 0.01:
        continue
    changed.append({'date': d, 'old': o, 'new': n})

print(f"\nDays changed: {len(changed)} of {len(all_dates)} traded-or-changed dates")
sym_changed = [c for c in changed if c['old'] and c['new'] and c['old']['symbol'] != c['new']['symbol']]
appeared = [c for c in changed if not c['old'] and c['new']]
disappeared = [c for c in changed if c['old'] and not c['new']]
print(f"  symbol changed: {len(sym_changed)}  appeared(only new): {len(appeared)}  disappeared(only old): {len(disappeared)}")

for c in changed:
    o = c['old']; n = c['new']
    os_ = f"{o['symbol']}({o['pnl']:+.0f},gap{o['gap_pct']:.0f})" if o else "-none-"
    ns_ = f"{n['symbol']}({n['pnl']:+.0f},gap{n['gap_pct']:.0f})" if n else "-none-"
    print(f"  {c['date']}: OLD {os_:28s} -> NEW {ns_}")

outp = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'outputs', 'trial173_2025_vwap_screen_diff.json'))
with open(outp, 'w') as f:
    json.dump({'old': {k: r_old[k] for k in ('total_trades','win_rate','total_pnl','profit_factor','max_drawdown')},
               'new': {k: r_new[k] for k in ('total_trades','win_rate','total_pnl','profit_factor','max_drawdown')},
               'changed': changed}, f, indent=2)
print("WROTE", outp)
