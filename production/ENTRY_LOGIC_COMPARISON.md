# Entry Logic Comparison: live_scanner.py vs simulator

## Key Finding: DIFFERENT CANDIDATE SELECTION

### Live Scanner (live_scanner.py)
```
1. Bars arrive from WebSocket
2. GapRunTracker.update(bar) detects cumulative 5%+ gain
3. If gain detected: add to _gaprun_qualified
4. Each minute (9:30am - entry_hour_end):
   - For each symbol in _gaprun_qualified:
     - Call _try_entry(symbol, bar, now_et)
     - Which calls evaluate_entry()
     - If signal returned: execute immediately
     - If no signal: log which gate is blocking
```

**Critical:** Line 300 in live_scanner.py:
```python
if (in_entry_window
        and not self._trade_manager.has_open_position()
        and symbol in self._gaprun_qualified):  # <-- ONLY evaluates gaprun symbols
    self._try_entry(symbol, bar, now_et)
```

### Simulator (simulation_engine.py)
```
1. Pre-build hot_symbols: scan ALL bars for the day, find those with 10%+ gain
2. For each minute in simulation:
   - Get all bars for that minute (filtered to hot_symbols)
   - For each symbol in candidates:
     - Check bar history length (need 7+)
     - Call evaluate_entry()
     - Track all signals by confidence score
   - Take the BEST signal (highest confidence)
     - (If multiple patterns fire, simulator ranks by confidence)
     - Live scanner takes the first signal that appears
```

**Critical:** Line 740 in simulation_engine.py:
```python
if self.hot_symbols and symbol not in self.hot_symbols:
    continue  # Skip if not pre-identified as hot
```

## Potential Issues Found

### Issue #1: Bar History Minimum
- **live_scanner:** Checks `if len(bars) < 5: return` (line 335)
- **entry_engine.py:** Calls `_check_5_pillars()` which has ITS OWN minimum
- **Simulator:** Checks `if len(history) < 7: continue` (line 746)

**Suspicion:** At 10:31 AM, does ANY have 5+ bars? If yes in real data but simulator gets 7+, they might diverge.

### Issue #2: Bar History Source
- **live_scanner:** Uses `_bar_history[symbol]` from WebSocket bars (line 334)
  - Bars arrive in real-time from Alpaca WebSocket
  - History starts building when WebSocket connection opens
  - Premarket bars (4am-8am) come from REST API snapshot
  - Then minute bars (8am+) come from WebSocket

- **Simulator:** Uses `get_minute_bars()` from database (line 330)
  - All bars loaded from DB at startup
  - Includes premarket + market hours
  - Guaranteed to have all historical bars

**Suspicion:** If WebSocket didn't connect at market open or had a delay, live_scanner might not have full history for ANY at 10:31.

### Issue #3: Relative Volume Calculation
- **live_scanner:** Uses `_get_relative_volume()` which calls DB queries (line 338)
- **entry_engine:** Uses `relative_volume` parameter passed in
- **Simulator:** Queries DB via `get_avg_volume_at_time_batch()` (line 789-794)

Both call DB, so should be identical IF the timing is the same.

**Question:** Does live_scanner calculate rel_vol at the right time? When does DB query run?

### Issue #4: Candidate Selection Order
- **live_scanner:** Evaluates symbols as they hit 5% gain
- **Simulator:** Evaluates all hot symbols at each minute, picks strongest

**Impact:** If ANY hit 5% gain at 10:28, but LXU/COHN/IBG hit it earlier, they get evaluated first. If the first stock's signal passes evaluate_entry(), live_scanner enters immediately. Simulator would see all three and pick the strongest.

**This might explain why live_scanner picked ANY (it came later and got first chance) while simulator picked LXU/COHN/IBG (they were stronger earlier).**

### Issue #5: Multiple Signals at Same Time
- **live_scanner:** If multiple symbols have bars at same timestamp, loops through them
  - No explicit ranking by confidence
  - Takes first signal that passes

- **Simulator:** Evaluates all candidates and explicitly picks best by confidence (line 831-835)
  ```python
  if (best_signal is None or
          entry_signal.pattern.confidence > best_signal.pattern.confidence):
      best_signal = entry_signal
  ```

## Tests to Run Tomorrow

To confirm which issue is the root cause:

1. **Log bar history size for ANY at 10:31**
   - Add to live_scanner._try_entry(): `logger.info(f"{symbol}: {len(bars)} bars")`
   - If < 7: history is too short, might cause different behavior

2. **Log all entry signals evaluated at 10:31**
   - Intercept evaluate_entry() calls
   - Log symbol, confidence, pattern for each
   - See which ones passed, which ones failed

3. **Log relative volume calculation**
   - Log rel_vol for ANY vs LXU/COHN/IBG at 10:31
   - Compare DB query results

4. **Log signal ranking**
   - If multiple signals fire at same minute, which wins?
   - Log the ranking: `signal1 confidence=0.85, signal2 confidence=0.75...`

## Hypothesis

**Most likely:** Issue #2 (bar history) or Issue #4 (candidate selection order).

- If ANY has fewer bars than LXU/COHN/IBG at 10:31, it might fail pattern detection
- If ANY's 5% gain was detected later than LXU's, it gets evaluated after LXU
- If LXU/COHN/IBG are evaluated first and their signals pass, they win in live_scanner
- In simulator, all are evaluated and the strongest wins

**Test this by checking:**
1. When was each stock's 5% gain detected in live trading?
2. How many bars did each stock have at 10:31?
3. What were the confidence scores for each?
