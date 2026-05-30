#!/usr/bin/env python3
"""
Compare entry signals that would fire at the EXACT TIMES of live trades.
Run: python production/compare_signals.py
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from utils.query_helpers import StockDataDB
from trading.entry_engine import evaluate_entry
from trading.models import ScannerConfig, EntryConfig
from datetime import datetime
import pytz

ET = pytz.timezone('US/Eastern')
db = StockDataDB()

target_date = datetime(2026, 3, 6).date()

# Get data for the 4 key stocks
symbols = ['ANY', 'LXU', 'COHN', 'IBG']
daily_bars = db.get_daily_bars(symbols, datetime(2026, 3, 3).date(), datetime(2026, 3, 5).date())
minute_dict = db.get_minute_bars(symbols, target_date, start_hour=9, end_hour=12)

prior_closes = {}
for symbol, bars in daily_bars.items():
    if bars:
        prior_closes[symbol] = float(bars[-1]['close'])

fundamentals = {}
for symbol in symbols:
    fundamentals[symbol] = {}  # Empty fundamentals for now

# Times when trades entered in LIVE session
trade_entries = [
    ('ANY', '10:31'),  # FLAT_TOP
    ('ANY', '10:52'),  # DIP_BUY
]

print("="*80)
print("COMPARING ENTRY SIGNALS AT LIVE TRADE TIMES")
print("="*80)

for symbol, time_str in trade_entries:
    hour, minute = map(int, time_str.split(':'))

    print(f"\n{symbol} at {time_str} ET (Live entry time)")
    print("-"*80)

    # Get bars up to that time for that symbol
    if symbol in minute_dict:
        all_bars = minute_dict[symbol]
        # Note: get_minute_bars returns bars with time in ET already
        bars_before = [b for b in all_bars
                      if (b['time'].hour < hour) or
                         (b['time'].hour == hour and b['time'].minute <= minute)]

        if len(bars_before) >= 7:
            # Build bar history (last 30 bars before entry)
            bar_history = bars_before[-30:]
            bar_dict = bars_before[-1]

            # Ensure bar dict has float values
            current_bar = {
                'time': bar_dict['time'],
                'symbol': bar_dict['symbol'],
                'open': float(bar_dict['open']),
                'high': float(bar_dict['high']),
                'low': float(bar_dict['low']),
                'close': float(bar_dict['close']),
                'volume': int(bar_dict['volume']),
            }

            # Calculate relative volume
            rel_vol = db.calculate_relative_volume(symbol, target_date,
                                                  current_time_et=ET.localize(datetime(2026, 3, 6, hour, minute, 0)))

            # Evaluate entry
            entry_signal = evaluate_entry(
                symbol=symbol,
                bar_history=bar_history[:-1],  # exclude current
                current_bar=current_bar,
                fundamentals=fundamentals.get(symbol, {}),
                prior_close=prior_closes.get(symbol),
                current_time=ET.localize(datetime(2026, 3, 6, hour, minute, 0)),
                relative_volume=rel_vol,
                scanner_config=ScannerConfig(),
                entry_config=EntryConfig(),
            )

            if entry_signal:
                pat = entry_signal.pattern
                print(f"  ENTRY SIGNAL: {pat.pattern_type:15s} @ ${pat.entry_price:.2f}")
                print(f"    Confidence: {pat.confidence:.2f}")
                print(f"    Stop: ${pat.stop_price:.2f} | Target1: ${pat.target1:.2f} | Target2: ${pat.target2:.2f}")
                print(f"    Relative volume: {rel_vol:.1f}x")
            else:
                print(f"  NO ENTRY SIGNAL")
                print(f"    (eval returned None - check gates)")
        else:
            print(f"  Not enough bars ({len(bars_before)} < 7)")

print("\n" + "="*80)
print("Now checking ALL 4 stocks at 10:31 ET to see full ranking")
print("="*80)

entry_signals_at_1031 = {}

for symbol in symbols:
    if symbol in minute_dict:
        all_bars = minute_dict[symbol]
        # 10:31 ET
        bars_before = [b for b in all_bars
                      if (b['time'].hour < 10) or
                         (b['time'].hour == 10 and b['time'].minute <= 31)]

        if len(bars_before) >= 7:
            bar_history = bars_before[-30:]
            bar_dict = bars_before[-1]

            # Ensure bar dict has float values
            current_bar = {
                'time': bar_dict['time'],
                'symbol': bar_dict['symbol'],
                'open': float(bar_dict['open']),
                'high': float(bar_dict['high']),
                'low': float(bar_dict['low']),
                'close': float(bar_dict['close']),
                'volume': int(bar_dict['volume']),
            }

            rel_vol = db.calculate_relative_volume(symbol, target_date,
                                                  current_time_et=ET.localize(datetime(2026, 3, 6, 10, 31, 0)))

            entry_signal = evaluate_entry(
                symbol=symbol,
                bar_history=bar_history[:-1],
                current_bar=current_bar,
                fundamentals=fundamentals.get(symbol, {}),
                prior_close=prior_closes.get(symbol),
                current_time=ET.localize(datetime(2026, 3, 6, 10, 31, 0)),
                relative_volume=rel_vol,
                scanner_config=ScannerConfig(),
                entry_config=EntryConfig(),
            )

            if entry_signal:
                entry_signals_at_1031[symbol] = {
                    'pattern': entry_signal.pattern.pattern_type,
                    'confidence': entry_signal.pattern.confidence,
                    'entry_price': entry_signal.pattern.entry_price,
                    'rel_vol': rel_vol,
                }

print(f"\nAt 10:31 ET, entry signals ranked by confidence:")
if entry_signals_at_1031:
    sorted_signals = sorted(entry_signals_at_1031.items(),
                           key=lambda x: x[1]['confidence'], reverse=True)
    for i, (symbol, data) in enumerate(sorted_signals):
        print(f"  {i+1}. {symbol:5s} {data['pattern']:15s} confidence={data['confidence']:.3f} rel_vol={data['rel_vol']:6.1f}x")
else:
    print("  No entry signals")

db.close()

print("\n" + "="*80)
print("KEY FINDINGS")
print("="*80)
print("""
If ANY has lower confidence than LXU/COHN/IBG at 10:31:
  - Simulator behavior is CORRECT (picked the strongest signal)
  - Live trading UNEXPECTED (picked weaker signal)
  - Root cause: live_scanner NOT using entry_engine.evaluate_entry()
                or evaluating stocks in different order

If ANY has highest confidence at 10:31:
  - Both should pick ANY
  - If live DID pick ANY and simulator DIDN'T:
    - Root cause: simulator's bar history seeding or timing differs
""")
