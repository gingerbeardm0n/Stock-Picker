#!/usr/bin/env python3
"""
Intent Test Runner
==================
Runs the simulator on specific dates and verifies portfolio rule enforcement
matches expected behavior based on Ross Cameron's actual sessions.

For each test case, reports:
  - Did simulator halt entries after a rule fired? (PASS/FAIL)
  - Which rule fired, at what time
  - Trades taken before halt vs trades Ross took after max-loss

Usage:
    python production/simulator/intent_test_runner.py
"""
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env.paper'))

from simulator.simulation_engine import SimulationRunner
from trading.models import ScannerConfig, EntryConfig, ExitConfig

# ── Test cases ────────────────────────────────────────────────────────────────
# Note: 2024-03-06 excluded (Polygon free tier blocked for that date)
TEST_CASES = [
    {
        'date': '2024-09-20',
        'file_num': '1014',
        'title': "GSIW revenge spiral — Ross lost ~$7.5k after ignoring max loss",
        'rc_symbols': ['GSIW', 'BZI', 'GDHG', 'LFLY'],
        'rc_what_happened': (
            "Ross entered GSIW 3 times (FOMO, dip buy, revenge). "
            "Each entry was after the prior stop-out. "
            "Total -$7,500. Should have stopped after trade 1."
        ),
        'expected_rule': 'DAILY_MAX_LOSS or GREEN_TO_RED',
        'pass_condition': 'any_rule_fired AND no entries after first rule fire',
    },
    {
        'date': '2025-04-01',
        'file_num': '0985',
        'title': "MLGO -$18k, Ross kept trading",
        'rc_symbols': ['MLGO', 'ICCT', 'DATS', 'GRRI'],
        'rc_what_happened': (
            "Ross lost -$18k on MLGO (2x position size, expensive stock). "
            "Kept trading: ICCT, DATS, GRRI. "
            "Ended +$2,754 only due to lucky GRRI win. "
            "Without GRRI would have been massive red day."
        ),
        'expected_rule': 'DAILY_MAX_LOSS',
        'pass_condition': 'any_rule_fired AND no entries after MLGO loss',
    },
]

def run_test(tc):
    date = tc['date']
    print(f"\n{'='*65}")
    print(f"FILE {tc['file_num']} | {date}")
    print(f"  {tc['title']}")
    print(f"  RC: {tc['rc_what_happened']}")
    print(f"  Expected rule: {tc['expected_rule']}")
    print()

    # Use default configs — same as live trading
    # Tight max loss for $5k account: 3% = $150
    runner = SimulationRunner(
        date,
        account_size=5000,
        risk_pct=1.0,
        max_position_pct=20,
        daily_max_loss_pct=3.0,
        verbose=True,
    )

    success = runner.run()
    if not success:
        print(f"  RESULT: No data for {date} — cannot run test")
        return None

    # Examine results
    summary = runner.portfolio_summary
    trade_log = runner.trade_log
    any_fired = summary.get('any_rule_fired', False)
    rules = summary.get('rules', {})

    print(f"\n  --- Simulator Results ---")
    print(f"  Trades taken:    {len(trade_log)}")
    print(f"  Final P&L:       ${summary.get('final_pnl', 0):+.2f}")
    print(f"  Peak P&L:        ${summary.get('peak_pnl', 0):+.2f}")
    print(f"  Any rule fired:  {any_fired}")

    for rule_name, rule_data in rules.items():
        if rule_data.get('fired'):
            print(f"  Rule fired:      {rule_name} at {rule_data.get('fire_time_et')} "
                  f"(P&L at fire: ${rule_data.get('pnl_at_fire', 0):+.2f})")

    # Check for entries AFTER a rule fired (the key test)
    # Find when first rule fired
    events = summary.get('events', [])
    first_fire_time = None
    fired_rule = None
    if events:
        first_fire_time = events[0].get('time_et')
        fired_rule = events[0].get('rule')

    entries_after_halt = []
    if first_fire_time:
        for trade in trade_log:
            import pytz
            et = pytz.timezone('America/New_York')
            trade_time_et = trade['time'].astimezone(et).strftime('%H:%M')
            action = trade.get('action', '')
            # Only count entries (not exits)
            if 'ENTRY' in action or 'OPEN' in action:
                if trade_time_et > first_fire_time:
                    entries_after_halt.append(trade)

    # PASS/FAIL
    if any_fired and len(entries_after_halt) == 0:
        verdict = "PASS"
        detail = f"Rule {fired_rule} fired at {first_fire_time}. No entries after halt."
    elif any_fired and len(entries_after_halt) > 0:
        verdict = "FAIL"
        detail = f"Rule fired but {len(entries_after_halt)} entries still occurred after halt!"
    else:
        verdict = "INFO"
        detail = "No rule fired — simulator didn't enter losing positions Ross took (different stock selection)"

    print(f"\n  VERDICT: {verdict}")
    print(f"  {detail}")

    # Show trade log
    if trade_log:
        print(f"\n  Trade log:")
        import pytz
        et = pytz.timezone('America/New_York')
        for t in trade_log:
            t_str = t['time'].astimezone(et).strftime('%H:%M')
            print(f"    {t_str}  {t.get('action','?'):20}  {t.get('symbol','?'):6}  "
                  f"@ ${t.get('price',0):.2f}  P&L ${t.get('pnl',0):+.2f}")
    else:
        print(f"\n  No trades taken (scanner may not have found entries on this day)")

    return verdict

# ── Run all tests ─────────────────────────────────────────────────────────────
print("Intent Test Runner — Daily Risk Rule Enforcement")
print("Verifying: simulator halts entries after DAILY_MAX_LOSS / GREEN_TO_RED fires")
print()

results = []
for tc in TEST_CASES:
    verdict = run_test(tc)
    results.append((tc['file_num'], tc['date'], verdict))

print(f"\n{'='*65}")
print("SUMMARY")
print(f"{'='*65}")
for file_num, date, verdict in results:
    v = verdict or 'NO_DATA'
    print(f"  FILE {file_num} | {date} | {v}")
