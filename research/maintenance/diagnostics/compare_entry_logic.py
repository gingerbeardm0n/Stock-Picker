#!/usr/bin/env python3
"""
Compare entry logic between live_scanner.py and entry_engine.py
Maps out the exact sequence of checks in each implementation.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

print("\n" + "="*100)
print("ENTRY LOGIC COMPARISON: live_scanner.py vs entry_engine.py")
print("="*100)

# ============================================================================
# PART 1: EXTRACT LIVE_SCANNER LOGIC
# ============================================================================
print("\n[LIVE_SCANNER.PY ENTRY LOGIC]")
print("-"*100)

with open('production/trading/live_scanner.py', 'r') as f:
    content = f.read()

# Find the main entry evaluation method
import re

# Look for the method that evaluates entry signals
pattern = r'def\s+(\w+).*?(?=\n    def\s|\nclass\s|\Z)'
methods = re.findall(pattern, content, re.DOTALL)

print("Methods in LiveScanner that might handle entry:")
for i, line in enumerate(content.split('\n')):
    if 'evaluate' in line.lower() and 'def ' in line:
        print(f"  Line {i+1}: {line.strip()}")
    if 'pattern' in line.lower() and ('detect' in line.lower() or 'signal' in line.lower()):
        print(f"  Line {i+1}: {line.strip()}")

# Get key methods
entry_method_lines = []
for i, line in enumerate(content.split('\n')):
    if 'def ' in line and ('entry' in line.lower() or 'scan' in line.lower()):
        entry_method_lines.append((i+1, line.strip()))

print("\nKey entry-related methods:")
for line_num, line in entry_method_lines:
    print(f"  Line {line_num}: {line}")

# ============================================================================
# PART 2: TRACE LIVE_SCANNER'S FLOW
# ============================================================================
print("\n\n[TRACING live_scanner.py ENTRY FLOW]")
print("-"*100)

print("""
Based on reading live_scanner.py, here's the entry flow:

1. Bars arrive via WebSocket or premarket scan
2. For each symbol in watchlist:
   a. Accumulate bar in _bar_history[symbol]
   b. Update _today_volume[symbol] (cumulative)
   c. Check if it's a gaprun (5%+ gain from prior close)
   d. If gaprun detected:
      - Add to _gaprun_qualified set
      - Log "INTRADAY GAPRUN DETECTED"
   e. Check timing gates (not before 9:30am ET, stop before entry_hour_end)
   f. Check if we're already in a position (no multi-position trading)
   g. Call evaluate_entry_signal() — this is where patterns are detected

3. In evaluate_entry_signal():
   - Passes bar_history, current_bar, relative_volume to evaluate_entry()
   - Returns PatternSignal or None
   - If signal found, calls trade_manager.enter_position()

Key characteristic: live_scanner uses evaluate_entry() from entry_engine
BUT the WATCHLIST is built separately (gaprun + premarket scan logic)
The question is: does live_scanner consider ALL gaprun/premarket symbols,
or does it skip some before they reach evaluate_entry()?
""")

# ============================================================================
# PART 3: EXTRACT ENTRY_ENGINE LOGIC
# ============================================================================
print("\n[ENTRY_ENGINE.PY ENTRY LOGIC]")
print("-"*100)

with open('production/trading/entry_engine.py', 'r') as f:
    engine_content = f.read()

print("""
Based on reading entry_engine.py, here's the entry evaluation sequence:

evaluate_entry() does this:
  1. Check 5 Pillars (price, gain, rel_vol, float, market cap, spread)
  2. Check time window (must be 9:30-11:00 AM by default)
  3. Check bar history minimum (need enough bars for patterns)
  4. Evaluate patterns (MICRO_PULLBACK, ABCD, DIP_BUY, FLAT_TOP, BULL_FLAG)
     - For each enabled pattern, detect_pattern() checks:
       - Has the pattern shape formed?
       - Is volume aligned with pattern rules?
       - Do price targets offer good risk/reward?
  5. Return best signal by confidence score

Key sequence:
  - 5 Pillars are GATES (fail here = no entry, skip to next symbol)
  - Patterns are EVALUATED (all enabled patterns checked, best one wins)
  - Time window is enforced (no entry outside 9:30-11:00 by default)
""")

# ============================================================================
# PART 4: IDENTIFY DIFFERENCES
# ============================================================================
print("\n\n[POTENTIAL DIFFERENCES]")
print("-"*100)

print("""
1. WATCHLIST CONSTRUCTION
   - live_scanner: Builds watchlist from gaprun + premarket scan
   - entry_engine: evaluate_entry() doesn't care about watchlist,
                   processes whatever symbol passed to it
   Question: Does live_scanner pass every symbol, or only gaprun/premarket ones?

2. TIME WINDOW
   - live_scanner: Has its own time check (entry_hour_end default 11am)
   - entry_engine: Also has time check (default 9:30-11:00)
   Potential issue: Different defaults? Let's check...

3. RELATIVE VOLUME CALCULATION
   - live_scanner: Uses _today_volume dict (manually accumulated)
   - entry_engine: Uses rel_vol parameter passed in (DB query result)
   Potential issue: Are both calculating the same way?

4. BAR HISTORY
   - live_scanner: _bar_history[symbol] updated as bars arrive
   - entry_engine: bar_history passed in as parameter
   Potential issue: Does live_scanner have enough bars by the time it evaluates?

5. PATTERN DETECTION
   - live_scanner: Calls detect_pattern() from trading/patterns.py
   - entry_engine: Also calls detect_pattern() from trading/patterns.py
   Should be identical, BUT confidence scores might differ due to bar history size

6. CONFIDENCE/RANKING
   - live_scanner: Takes FIRST signal that passes?
   - entry_engine: Takes BEST signal (highest confidence)?
   Potential issue: If multiple patterns fire, which wins?
""")

# ============================================================================
# PART 5: SPECIFIC CODE INSPECTION
# ============================================================================
print("\n\n[CODE INSPECTION - SPECIFIC DIFFERENCES]")
print("-"*100)

# Find evaluate_entry_signal in live_scanner
lines = content.split('\n')
for i, line in enumerate(lines):
    if 'def evaluate_entry_signal' in line or 'def _evaluate_entry' in line:
        print(f"\nFound entry evaluation at line {i+1}:")
        # Print the next 30 lines
        for j in range(i, min(i+40, len(lines))):
            print(f"{j+1:4d}  {lines[j]}")
        break

print("\n\n[NEXT STEPS TO DIAGNOSE]")
print("-"*100)

print("""
To understand the ACTUAL difference, we need to:

1. Log what symbols are in live_scanner's gaprun/premarket lists at 10:31
   - Were LXU, COHN, IBG in this list?
   - Was ANY in this list?

2. Log which symbols make it to evaluate_entry() in live_scanner
   - Does it evaluate ALL symbols or only gaprun/premarket?

3. Log what evaluate_entry() returns for each symbol at 10:31
   - What's the confidence score for ANY vs LXU/COHN/IBG?
   - Which pattern fired for each?

4. Check if live_scanner picks the strongest signal or just the first one

5. Compare bar history sizes
   - Does live_scanner have enough bars at 10:31?
   - How many bars in _bar_history[ANY] at 10:31?

To do this, we can add logging to live_scanner.py and run it again tomorrow.
Or we can read the code more carefully and find the exact issue.
""")

print("\n" + "="*100)
print("END OF COMPARISON")
print("="*100 + "\n")
