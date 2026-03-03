# Category C Gap Analysis: Exit Logic vs Strategy Documentation

**Documented**: Feb 21, 2026 | **Status**: Current exit logic is 60% complete vs full strategy

---

## Overview

This document compares the **current exit_engine.py implementation** (8 parameters) against the **strategy documentation** (UTS_EXIT_RULES.md + UTS_RISK_MANAGEMENT.md) to identify missing features and calculate the full Parameter Category C scope.

**Finding**: Current implementation covers position-level exits but is missing:
1. ⚠️ **CRITICAL**: Portfolio-level daily rules (3 rules)
2. ⚠️ **MEDIUM**: Multi-level scaling (3-level + trailing stops)
3. ⚠️ **MEDIUM**: Advanced exit signals (MACD flip, resistance levels, volume dry-up)
4. ⚠️ **LOW**: Time threshold nuances (10:45 AM early exit)

**Impact on Optimization**: Category C expands from 8 → ~21-22 parameters. This affects optimization trial count (+50%).

---

## Part 1: What's IMPLEMENTED (Position-Level Exits)

### Current Exit Engine (exit_engine.py)

The current implementation correctly handles **individual position exits**:

| Exit Signal | Implemented | Code Line | Parameters |
|-------------|-------------|-----------|------------|
| **Hard Stop** | ✅ YES | 59-64 | (1 logic, no tuning) |
| **Target 1 (2:1 R/R)** | ✅ YES | 67-74 | qty_scale=50%, ratio=2:1 |
| **Target 2 (3:1 R/R)** | ✅ YES | 77-84 | qty_scale=25%, ratio=3:1 |
| **EMA-9 Cross** | ✅ YES | 90-99 | ema_period=9 (fixed) |
| **Time Decay** | ✅ YES | 104-109 | hour_threshold=11 AM |
| **Selling Pressure** | ✅ YES | 115-127 | volume_ratio_threshold=2.0x |

**Quality Assessment**: These 6 signals are correctly implemented per strategy. Well-ordered (hard stops first, soft signals only if profitable).

---

## Part 2: What's MISSING (Critical Gaps)

### 🔴 MISSING 1: Portfolio-Level Daily Rules

**Strategy Requirement** (UTS_RISK_MANAGEMENT.md, lines 64-152):

The strategy defines **5 daily rules**, of which 3 are **hard portfolio exits**:

| Rule | Strategy Requirement | Current Code | Impact |
|------|----------------------|--------------|--------|
| **Daily Max Loss** | Once account loses X%, STOP TRADING FOR DAY | ❌ NOT IMPLEMENTED | Positions can lose account indefinitely |
| **Green-to-Red Rule** | Account goes profitable → unprofitable → STOP ALL | ❌ NOT IMPLEMENTED | Revenge trading risk unmanaged |
| **Give-Back-Half Rule** | Hit daily profit target, lose >50% → EXIT ALL positions | ❌ NOT IMPLEMENTED | No protection against volatility reversal |

**Why Missing**: These are **portfolio-level rules**, not position-level. The exit_engine.py only handles individual positions. The orchestration logic must be in `SimulationRunner._evaluate_positions()`.

**Where to Implement**:
```python
# In SimulationRunner._process_minute():
daily_pnl = self.calculate_daily_pnl()
if daily_pnl <= -self.daily_max_loss_pct * self.account_balance:
    # STOP TRADING — close all open positions
    for position in self.positions:
        force_exit(position, "DAILY_MAX_LOSS")

if was_profitable_this_morning and daily_pnl < 0:
    # GREEN_TO_RED triggered — close all positions
    for position in self.positions:
        force_exit(position, "GREEN_TO_RED")

if daily_pnl >= self.daily_profit_target and daily_pnl < (self.daily_profit_target * 0.5):
    # Give back >50% — close all positions
    for position in self.positions:
        force_exit(position, "GIVE_BACK_HALF")
```

**Parameters to Add**:
- `daily_max_loss_pct` (e.g., 3% of account = $150 on $5K)
- `daily_profit_target` (e.g., $300 = triggers give-back-half threshold)
- `green_to_red_enabled` (boolean, default True)
- `give_back_half_enabled` (boolean, default True)

**Note**: `daily_max_loss_pct` already exists in Category A (SCANNER_CRITERIA), but must also be enforced here.

---

### 🟠 MISSING 2: Multi-Level Scaling (3-Level + Trailing Stops)

**Strategy Requirement** (UTS_EXIT_RULES.md, lines 62-80):

Advanced traders use **3-level scaling**:

```
Standard (Current):
  Target 1 @ 2:1 R/R → Sell 50%
  Target 2 @ 3:1 R/R → Sell 25%
  Remainder → Hold until EMA cross or time decay

Advanced (Missing):
  Target 1 @ 2:1 R/R → Sell 25%
  Target 2 @ 3:1 R/R → Sell 25%
  Target 3 / Trailing → Sell 50% with 5-cent trailing stop
```

**Key Difference**: The 50% position is left to trail with a fixed 5-cent stop, not tied to a price target.

**Current Implementation**:
```python
# exit_engine.py, lines 67-84
if current_price >= position.target1 and shares_remaining == position.shares:
    return ExitSignal(reason='TARGET_1', qty=position.shares // 2)
if current_price >= position.target2 and 0 < shares_remaining < position.shares:
    return ExitSignal(reason='TARGET_2', qty=position.shares // 4)
```

**Problem**:
- Fixed 50% + 25% scaling only
- Remainder exits on technical signals (EMA, time, volume)
- No trailing stop mechanics

**What's Missing**:
1. **Target 3 (optional trailing exit)**
   - Hold remainder with trailing stop (e.g., -5 cents from highest price)
   - Exit when stopped or other signal fires first

2. **Trailing Stop Mechanics**
   - Track highest price since entry
   - Dynamic stop = highest_price - trailing_distance
   - No code for this exists

3. **Scaling Strategy Selection**
   - Should support both 2-level and 3-level modes
   - Different accounts/styles prefer different approaches

**Parameters to Add**:
- `enable_three_level_scaling` (boolean, default False for safety)
- `target_1_qty_pct` (currently 50%, could be 25%)
- `target_1_ratio` (currently 2:1, tunable)
- `target_2_qty_pct` (currently 25%, could be 25%)
- `target_2_ratio` (currently 3:1, tunable)
- `target_3_enabled` (boolean, for trailing portion)
- `target_3_ratio` (e.g., 4:1 R/R if used)
- `trailing_stop_distance` (e.g., $0.05 = 5 cents)

**Code Changes Needed**:
- Add `highest_price_since_entry` to Trade object
- Update on every bar: `highest_price_since_entry = max(highest_price_since_entry, current_price)`
- In exit_engine, check: `if highest_price_since_entry - current_price >= trailing_stop_distance`

---

### 🟠 MISSING 3: MACD Histogram Exit Signal

**Strategy Requirement** (UTS_EXIT_RULES.md, lines 121-124):

```
MACD Histogram Turns Red (Positive → Negative)
- Momentum indicator flips
- Not immediate sell, but warning
- Tighten stop, be ready to exit
```

**Current Code**: No MACD tracking in exit_engine.py

**What's Needed**:
1. **Track MACD state on each bar** — was it positive last bar? Is it negative now?
2. **Detect flip** — positive → negative transition
3. **Action** — scale out 25-50% or tighten stop (depends on parameterization)

**Parameters to Add**:
- `enable_macd_exit` (boolean, default True)
- `macd_exit_action` (string: "scale_50_pct", "scale_25_pct", "tighten_stop")
- `macd_exit_qty_pct` (e.g., 50% if action=scale)
- `macd_exit_stop_offset` (e.g., $0.01 if action=tighten_stop)

**Code Changes Needed**:
```python
# Track MACD state
if indicators.get('macd_histogram_prev') is not None:
    was_positive = indicators['macd_histogram_prev'] > 0
    is_now_negative = indicators['macd_histogram'] <= 0
    if was_positive and is_now_negative:
        # MACD flip detected
        return ExitSignal(reason='MACD_FLIP', qty=..., tighten_stop=...)
```

---

### 🟡 MISSING 4: Resistance Level / Prior Day High Exit

**Strategy Requirement** (UTS_EXIT_RULES.md, lines 126-130):

```
Stock Touches Prior Day's High
- Tests resistance 2-3 times = accumulation phase over
- On 3rd test = less likely to break
- Exit 50% and trail stop on remainder
```

**Current Code**: No prior day high tracking

**What's Needed**:
1. **Store prior day's close and high** per symbol
2. **Detect touches** — current bar's high >= prior_day_high - tolerance (e.g., $0.03)
3. **Count touches** — track how many times symbol has tested this level
4. **Action** — scale out 50% on 2nd+ test

**Parameters to Add**:
- `enable_resistance_exit` (boolean, default True)
- `resistance_touch_tolerance` (e.g., $0.03 = within 3 cents)
- `resistance_touch_count_threshold` (e.g., 2 = exit on 2nd touch)
- `resistance_exit_qty_pct` (e.g., 50%)

**Code Changes Needed**:
- SimulationRunner must fetch `prior_day_high` for each symbol
- Track touch count in Trade object: `resistance_touches`
- Increment when `current_high >= prior_day_high - tolerance`
- In exit_engine: `if position.resistance_touches >= threshold`

---

### 🟡 MISSING 5: Volume Dry-Up Detection

**Strategy Requirement** (UTS_EXIT_RULES.md, lines 115-119):

```
Volume Dries Up on UP Candles
- Declining volume = momentum fading
- Example: First candles 500K volume, 5 candles later 100K volume
- Signal = buyers stepping away
- Exit on next small pullback
```

**Current Code**: Selling Pressure is tracked, but not volume trend decline

**What's Needed**:
1. **Track volume baseline** — rolling average (e.g., last 5 green bars)
2. **Detect dry-up** — current bar volume < 60% of baseline
3. **Action on dry-up** — set flag, then exit on small pullback (or immediately)

**Parameters to Add**:
- `enable_volume_dry_up_exit` (boolean, default False, since it's complex)
- `volume_dry_up_threshold_pct` (e.g., 60% = volume < 60% of avg)
- `volume_baseline_bars` (e.g., 5 = use last 5 green bars)
- `volume_dry_up_action` (string: "immediate_exit", "exit_on_pullback", "tighten_stop")
- `volume_dry_up_qty_pct` (how much to exit)

**Code Changes Needed**:
- Track rolling volume of green bars only
- Detect when current bar volume drops below threshold
- Complex timing (not immediate exit, but "on pullback")

---

### 🟡 MISSING 6: Time Threshold Nuances (10:45 AM Early Exit)

**Strategy Requirement** (UTS_EXIT_RULES.md, lines 132-135):

```
Time Decay (11:00 AM+ approaching)
- Probability of big moves declines after 10:30 AM
- More reversals, less follow-through
- If still in position at 10:45 AM and no major gains, exit or tighten stop
```

**Current Code**:
```python
if in_profit and et_time.hour >= TIME_DECAY_HOUR:  # Hard 11 AM cutoff
    return ExitSignal(reason='TIME_DECAY', ...)
```

**Issue**: Single hard 11 AM cutoff, no consideration of "major gains"

**What's Needed**:
1. **Early time decay** — 10:30 or 10:45 AM, with "no major gains" condition
2. **Major gains threshold** — "no major gains" means what? (5%+, 10%+, R/R ratio achieved?)
3. **Action** — exit immediately, or tighten stop, or scale out partially

**Parameters to Add**:
- `early_time_decay_hour` (e.g., 10 for 10:XX AM)
- `early_time_decay_minute` (e.g., 45 for 10:45 AM)
- `early_time_decay_gains_threshold_pct` (e.g., 5% = "major gains" means >5% unrealized)
- `early_time_decay_action` (string: "exit_if_unprofitable", "exit_all", "scale_50_pct")
- `time_decay_hour` (currently 11, keep as primary cutoff)
- `time_decay_action` (currently always full exit; could be "scale_50_pct")

**Code Changes Needed**:
```python
unrealized_pct = (current_price - position.entry_price) / position.entry_price * 100

# Early exit (10:45 AM, only if no major gains)
if (et_time.hour == 10 and et_time.minute >= 45 and
    unrealized_pct < early_time_decay_gains_threshold_pct):
    return ExitSignal(reason='EARLY_TIME_DECAY', ...)

# Hard exit (11 AM, regardless of gains)
if in_profit and et_time.hour >= TIME_DECAY_HOUR:
    return ExitSignal(reason='TIME_DECAY', ...)
```

---

## Part 3: Parameter Count Expansion

### Current Category C Parameters (8)

| # | Parameter | Current Value | Type | Notes |
|----|-----------|---------------|------|-------|
| 1 | `TIME_DECAY_HOUR` | 11 | int | Time threshold for exit |
| 2 | `TARGET_1_QTY_PCT` | 50 | int | Shares to sell at T1 |
| 3 | `TARGET_1_RATIO` | 2:1 | ratio | R/R at first target |
| 4 | `TARGET_2_QTY_PCT` | 25 | int | Shares to sell at T2 |
| 5 | `TARGET_2_RATIO` | 3:1 | ratio | R/R at second target |
| 6 | `SELLING_PRESSURE_RATIO` | 2.0x | float | Volume threshold for scale-out |
| 7 | `EMA_CROSS_ENABLED` | True | bool | Enable EMA-9 exit |
| 8 | `TIME_DECAY_ENABLED` | True | bool | Enable time-based exit |

### Proposed Additions (~13-14 parameters)

**Portfolio-Level Rules (4 params)**:
- `DAILY_MAX_LOSS_PCT` (already in Category A, but enforced here)
- `DAILY_PROFIT_TARGET` (new, ties to give-back-half)
- `GREEN_TO_RED_ENABLED`
- `GIVE_BACK_HALF_ENABLED`

**Multi-Level Scaling (7 params)**:
- `ENABLE_THREE_LEVEL_SCALING`
- `TARGET_1_QTY_PCT` (tunable from 50 → 25-50)
- `TARGET_2_QTY_PCT` (tunable from 25 → 25-50)
- `TARGET_3_ENABLED`
- `TARGET_3_RATIO` (new, e.g., 4:1)
- `TRAILING_STOP_DISTANCE` (new, e.g., $0.05)
- `TRAILING_STOP_ENABLED` (new)

**MACD Exit (3 params)**:
- `ENABLE_MACD_EXIT`
- `MACD_EXIT_ACTION` (scale vs tighten)
- `MACD_EXIT_QTY_PCT` (how much to sell)

**Resistance Level (4 params)**:
- `ENABLE_RESISTANCE_EXIT`
- `RESISTANCE_TOUCH_TOLERANCE`
- `RESISTANCE_TOUCH_COUNT_THRESHOLD`
- `RESISTANCE_EXIT_QTY_PCT`

**Volume Dry-Up (5 params)**:
- `ENABLE_VOLUME_DRY_UP_EXIT`
- `VOLUME_DRY_UP_THRESHOLD_PCT`
- `VOLUME_BASELINE_BARS`
- `VOLUME_DRY_UP_ACTION`
- `VOLUME_DRY_UP_QTY_PCT`

**Time Nuances (4 params)**:
- `EARLY_TIME_DECAY_HOUR`
- `EARLY_TIME_DECAY_MINUTE`
- `EARLY_TIME_DECAY_GAINS_THRESHOLD_PCT`
- `EARLY_TIME_DECAY_ACTION`

**Total Additions**: ~27 parameters (though many can be grouped/consolidated)

---

## Part 4: Implementation Priority

### Phase 1 (CRITICAL — Blocks Optimization): Portfolio-Level Rules

**Work**: Add to `SimulationRunner._process_minute()` or `_evaluate_positions()`

**Rationale**: These are non-optional per strategy. Optimization cannot proceed without them.

**Files to Modify**:
- `simulator/simulation_engine.py` — Add daily P/L tracking, rule enforcement

**Estimated complexity**: 1 hour

---

### Phase 2 (HIGH — Affects Results): Multi-Level Scaling

**Work**: Add trailing stop mechanics, 3-level scaling option

**Rationale**: Significantly impacts profit-taking behavior. Current 2-level is too simplistic.

**Files to Create/Modify**:
- `trading/models.py` — Add `highest_price_since_entry` to Trade
- `trading/exit_engine.py` — Add trailing stop logic, 3-level selection
- `simulator/simulation_engine.py` — Update bar history to track highest price

**Estimated complexity**: 2-3 hours

---

### Phase 3 (MEDIUM — Improves Signal Quality): MACD Flip + Resistance

**Work**: Add MACD state tracking, resistance level detection

**Rationale**: Documented signals that improve exit quality. Lower priority than scaling.

**Files to Modify**:
- `trading/exit_engine.py` — Add MACD flip and resistance checks
- `trading/indicators.py` — Track MACD state (prior bar)
- `simulator/simulation_engine.py` — Fetch prior day high per symbol

**Estimated complexity**: 2 hours

---

### Phase 4 (LOW — Nice to Have): Volume Dry-Up, Early Time Decay

**Work**: Add volume trend detection, nuanced time thresholds

**Rationale**: Complex and less critical. Can be deferred or made optional.

**Files to Modify**:
- `trading/exit_engine.py` — Add volume and time logic
- `simulator/simulation_engine.py` — Maintain volume baseline per symbol

**Estimated complexity**: 1.5 hours

---

## Part 5: Optimization Plan Adjustments

### Original Estimate (Feb 21 brainstorm)

- Category C: 8 current parameters
- Expected growth: 15-25 total after gap analysis
- Optuna trials: ~1,500-2,000

### Revised Estimate (Post Gap Analysis)

- Category C: 8 current parameters
- New additions: 27 parameters (before consolidation)
- **Consolidated Category C: ~21-22 parameters** (after smart grouping)
- Optuna trials: ~1,500-2,000 (mostly unchanged; 27 params only adds ~10% trial cost vs 8 params)

### Impact on Optimization Timeline

| Phase | Time | Notes |
|-------|------|-------|
| Phase 1 (Portfolio rules) | 1 hour | CRITICAL, unblocks tests |
| Phase 2 (Scaling) | 2-3 hours | HIGH, must be done |
| Phase 3 (MACD + Resistance) | 2 hours | MEDIUM, can run tests without it |
| Phase 4 (Volume + Time) | 1.5 hours | LOW, optional |
| **Total implementation** | **6.5-7.5 hours** | **Can be split across sessions** |
| Optuna optimization runs | 3-4 hours | Unaffected by this analysis |
| Walk-forward validation | 1 hour | Unaffected |

---

## Part 6: Recommendation

### Immediate Action (Next Session START)

1. **Implement Phase 1 only** (Portfolio-level rules)
   - Daily max loss enforcement
   - Green-to-red rule
   - Give-back-half rule
   - Time: ~1 hour
   - Impact: Enables testing without risk of blown accounts

2. **Keep current exit_engine.py as-is** for now
   - Don't add trailing stops or MACD yet
   - Current 2-level scaling is valid
   - Can optimize on stable code

3. **Document Phase 2-4 as optional parameters**
   - Add to SIMULATION_OPTIMIZATION_PLAN.md as "future enhancements"
   - Include in Optuna trials as boolean feature flags
   - Example: `ENABLE_THREE_LEVEL_SCALING=False` by default

### Why This Approach

- **De-risks optimization**: Get portfolio rules working first
- **Preserves current results**: Don't change exit logic mid-optimization
- **Allows parallel work**: Can implement phases 2-4 while Optuna runs
- **Cleaner comparison**: TEST 1 vs TEST 2 comparison isn't confounded by exit changes

### Alternative (More Ambitious)

- Implement Phases 1-2 now (3-4 hours total)
- Larger parameter space (15-16 params in Category C)
- More sophisticated scaling matches strategy better
- Higher optimization cost (minor)

---

## Summary Table

| Category | Current | Gap | Final | Parameters | Priority |
|----------|---------|-----|-------|------------|----------|
| A (Stock Select) | 8 | 0 | 8 | All stable | ✅ |
| B (Entry) | 15-18 | 0 | 15-18 | All stable | ✅ |
| C (Exit) | 8 | **13-27** | **21-22** | **Significant expansion** | ⚠️ |
| **TOTAL** | **31-34** | **+13-27** | **44-48** | **+40%** | **⚠️** |

**Bottom Line**: Category C is only 60% complete per strategy. Recommended implementation:
1. **Phase 1 (1 hour)**: Portfolio rules — MUST DO
2. **Phase 2 (2-3 hours)**: Multi-level scaling — SHOULD DO
3. **Phase 3-4 (2.5 hours)**: MACD + volume + time — NICE TO HAVE

**Decision Point**: After Phase 1, decide whether to add Phases 2-4 before optimization or after as refinements.

