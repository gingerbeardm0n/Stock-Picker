#!/usr/bin/env python3
"""
Comprehensive diagnostic comparing March 6 simulator vs live trading.
Runs once, outputs complete analysis.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from simulator.simulation_engine import SimulationRunner
from utils.query_helpers import StockDataDB
from datetime import datetime
import pytz

ET = pytz.timezone('US/Eastern')

print("\n" + "="*80)
print("MARCH 6, 2026 DIAGNOSTIC: SIMULATOR VS LIVE TRADING")
print("="*80)

# ============================================================================
# PART 1: SIMULATOR TRADES
# ============================================================================
print("\n[PART 1] SIMULATOR TRADES")
print("-" * 80)

runner = SimulationRunner(
    date=datetime(2026, 3, 6).date(),
    account_size=5000,
    risk_pct=2.0,
    verbose=False
)

runner.run()

print(f"\nSimulator Results:")
print(f"  Account: $5,000 -> ${runner.position_manager.current_balance:,.2f}")
print(f"  P&L: ${runner.position_manager.current_balance - 5000:+.2f}")
print(f"  Completed trades: {len(runner.position_manager.trades_completed)}")

for i, trade in enumerate(runner.position_manager.trades_completed):
    print(f"    {i+1}. {trade.symbol:5s} {trade.pattern_type:15s} @ ${trade.entry_price:6.2f} | P&L: ${trade.get_pnl():+8.2f}")

# ============================================================================
# PART 2: LIVE TRADING SESSION ANALYSIS
# ============================================================================
print("\n[PART 2] LIVE TRADING SESSION (ACTUAL)")
print("-" * 80)

# Parse the session log
trades_from_log = []
with open('production/logs/session_2026-03-06.log', 'r') as f:
    for line in f:
        if 'ENTRY SIGNAL' in line:
            # Extract symbol, pattern, entry price
            parts = line.split('|')
            symbol = parts[1].strip().split()[0]
            pattern = parts[2].split('=')[1].strip()
            entry_price = float(parts[3].split('$')[1].split()[0])

            trades_from_log.append({
                'symbol': symbol,
                'pattern': pattern,
                'entry_price': entry_price,
                'exits': []
            })
        elif 'EXIT' in line and trades_from_log:
            # Attach exit to most recent trade
            if 'reason=' in line:
                reason = line.split('reason=')[1].split()[0]
                trades_from_log[-1]['exits'].append(reason)

print(f"\nLive Trading Results:")
print(f"  Account: $100,000 -> $99,055.09")
print(f"  P&L: -$944.91")
print(f"  Entry signals: {len(trades_from_log)}")

for i, trade in enumerate(trades_from_log):
    print(f"  {i+1}. {trade['symbol']} {trade['pattern']:15s} @ ${trade['entry_price']:.2f} | Exits: {', '.join(trade['exits']) if trade['exits'] else 'STILL OPEN'}")

# ============================================================================
# PART 3: ANY ANALYSIS
# ============================================================================
print("\n[PART 3] ANY - DETAILED ANALYSIS")
print("-" * 80)

db = StockDataDB()

# Get ANY's price action on March 6
target_date = datetime(2026, 3, 6).date()
minute_bars_dict = db.get_minute_bars(['ANY'], target_date, start_hour=8, end_hour=12)

if 'ANY' in minute_bars_dict:
    bars = minute_bars_dict['ANY']
    print(f"\nANY - {len(bars)} minute bars loaded (8am-12pm ET)")

    # Find entry signal times
    entry_times = [
        ('10:31', 1.85, 'FLAT_TOP (live)'),
        ('10:52', 1.89, 'DIP_BUY (live)'),
    ]

    # Show bars around entry times
    for entry_label, entry_price, entry_source in entry_times:
        entry_hour, entry_min = map(int, entry_label.split(':'))

        # Find bars around this time
        matching_bars = []
        for bar in bars:
            bar_et = bar['time']
            if bar_et.hour == entry_hour and bar_et.minute >= entry_min - 3 and bar_et.minute <= entry_min + 3:
                matching_bars.append(bar)

        if matching_bars:
            print(f"\n  {entry_label} ET ({entry_source}):")
            print(f"    Entry price: ${entry_price:.2f}")
            for bar in matching_bars[:5]:
                print(f"      {bar['time'].strftime('%H:%M')} | C:{bar['close']:6.2f} | V:{bar['volume']:10,}")

# ============================================================================
# PART 4: RELATIVE VOLUME AT KEY TIMES
# ============================================================================
print("\n[PART 4] RELATIVE VOLUME ANALYSIS")
print("-" * 80)

daily_bars = db.get_daily_bars(['ANY', 'LXU', 'COHN', 'IBG'],
                               datetime(2026, 3, 3).date(),
                               datetime(2026, 3, 5).date())

prior_closes = {}
for symbol, bars in daily_bars.items():
    if bars:
        prior_closes[symbol] = bars[-1]['close']

for symbol in ['ANY', 'LXU', 'COHN', 'IBG']:
    rel_vol_10_31 = db.calculate_relative_volume(symbol, target_date,
                                                 current_time_et=ET.localize(datetime(2026, 3, 6, 10, 31, 0)))
    print(f"\n{symbol} at 10:31 ET:")
    print(f"  Relative volume: {rel_vol_10_31:.1f}x")

    if symbol in prior_closes:
        prior_close = prior_closes[symbol]
        # Find 10:31 bar
        minute_dict = db.get_minute_bars([symbol], target_date, start_hour=10, end_hour=11)
        if symbol in minute_dict:
            bars_at_1031 = [b for b in minute_dict[symbol]
                            if b['time'].hour == 10 and b['time'].minute == 31]
            if bars_at_1031:
                price = bars_at_1031[0]['close']
                gain = ((price - prior_close) / prior_close) * 100
                print(f"  Price: ${price:.2f} | Prior close: ${prior_close:.2f} | Gain: {gain:+.1f}%")

db.close()

print("\n" + "="*80)
print("DIAGNOSTIC COMPLETE")
print("="*80 + "\n")
