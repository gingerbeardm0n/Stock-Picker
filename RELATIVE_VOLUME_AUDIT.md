# Relative Volume Calculation Audit

**Date**: Feb 18, 2026
**Status**: CRITICAL BUG FOUND + CRITERIA ISSUES

---

## Executive Summary

### The Problem
Relative volume is calculated **differently in different parts of the codebase**:
- ✅ **backtest_scanner.py**: CORRECT (time-of-day aware)
- ❌ **simulation_engine.py**: WRONG (uniform distribution assumption)
- ❌ **CRITERIA**: min_avg_volume 500K is NOT from Ross Cameron

### Impact
- Simulator produces inaccurate results (overstates relative volume)
- Sanity check shows low relative volumes (0.56x, 1.96x) because simulator calculation is wrong
- Scanner misses real movers due to overly strict criteria

---

## Detailed Audit

### 1. backtest_scanner.py (CORRECT ✅)

**Location**: `database/backtest_scanner.py` lines 228-279

**Formula**:
```python
avg_vol_at_time = db.get_avg_volume_at_time_batch(
    symbols, date, scan_hour, scan_minute, lookback_days=20
)
relative_volume = total_volume / avg_vol_at_time if avg_vol_at_time > 0 else 0.0
```

**What it does**:
- Calls `get_avg_volume_at_time_batch()` from query_helpers.py
- This method gets the average volume from 4am to the SAME HOUR:MINUTE over the past 20 days
- Then divides today's volume-so-far by that average
- **This is CORRECT**

**Database Method**: `query_helpers.py` lines 321-385

The SQL query:
1. Gets historical data from past N days
2. Filters for times between 4am and current_hour:current_minute
3. Sums volumes per day
4. Averages across all those days
5. Returns that as the denominator

✅ **VERDICT**: This is the correct formula

---

### 2. simulation_engine.py (WRONG ❌)

**Location**: `database/simulation_engine.py` lines 448-494

**Formula**:
```python
avg_daily_vol = self._calculate_avg_volume(symbol)  # 20-day average DAILY volume
expected_minute_vol = avg_daily_vol / 480  # Divide by 480 minutes
return current_vol / expected_minute_vol
```

**What it does** (WRONG):
- Gets 20-day average **daily** volume
- Divides by 480 (minutes in 4am-12pm window)
- Assumes every minute has equal volume
- **This is WRONG because 4am ≠ 9:30am ≠ 12pm**

**Example of the problem**:
- Stock ABC: 10M shares average daily volume
- At 4:30am: 10,000 shares traded (normal for 4am)
- Relative volume calc: 10,000 / (10M / 480) = 10,000 / 20,833 = 0.48x
- But this is actually HIGH for 4am! Should be 5x+

❌ **VERDICT**: This calculation is fundamentally wrong

---

### 3. sanity_check.py (Inherits scanner's calculation ✅)

**Location**: `database/sanity_check.py`

- Uses `backtest_single_day()` which calls backtest_scanner.py
- So it gets the CORRECT relative volume calculation
- This is why Feb 10 results show low rel vols (0.56x, 1.96x) - the scanner rejected them fairly

✅ **VERDICT**: sanity_check is correct (it uses the correct scanner)

---

### 4. CRITERIA Issues (NOT FROM ROSS)

**Location**: `database/backtest_scanner.py` line 30, `simulation_engine.py` line 39

```python
'min_avg_volume': 500_000,      # This is NOT from Ross Cameron
'min_morning_volume': 100_000,  # This is correct (user's intent)
```

**Problems**:
1. **500K average volume** is NOT a Ross Cameron metric
2. **User's intent** is "minimum 100K shares traded in premarket total", not "minimum 500K daily average"
3. These two are DIFFERENT:
   - Avg volume 500K: excludes many good small-cap plays
   - Morning premarket 100K: allows low-volume stocks to show high relative volume

**Example**:
- Stock with 200K average daily volume (< 500K threshold) - REJECTED
- But if trading 100K shares by 9:15am, relative volume could be 10x+
- Should be INCLUDED, not REJECTED

❌ **VERDICT**: Criteria is too strict and not aligned with Ross Cameron

---

## Required Fixes

### Fix 1: Update CRITERIA

```python
SCANNER_CRITERIA = {
    'min_price': 1.00,              # was 2.00 (allow penny stocks/gappers)
    'max_price': 20.0,
    'min_avg_volume': 100_000,      # was 500_000 (LOW volume + HIGH current = good signal)
    'min_morning_volume': 100_000,  # 100K shares in premarket is enough
    'min_relative_volume': 3.0,     # was 5.0 (will revert to 5 once simulator is fixed)
    'min_premarket_gain': 10.0,     # Correct
    'max_float': 50_000_000,        # was 20_000_000 (relax for small caps)
    'max_market_cap': 500_000_000,  # Correct
}
```

### Fix 2: Update simulation_engine.py

Replace `_calculate_relative_volume_at_minute()` to call the database method instead:

```python
def _calculate_relative_volume_at_minute(self, symbol, current_time, current_bars):
    """
    Calculate relative volume using time-of-day adjusted method
    Relative Volume = (volume at time X today) / (avg volume at time X over last 30 days)
    """
    current_bar = next((b for b in current_bars if b['symbol'] == symbol), None)
    if not current_bar:
        return 0

    current_vol = float(current_bar['volume'])

    # Get historical average volume at this same time of day
    with StockDataDB() as db:
        avg_vol_at_time = db.get_avg_volume_at_time_batch(
            [symbol],
            self.date,
            current_time.hour,
            current_time.minute,
            lookback_days=20
        )

    avg_vol = avg_vol_at_time.get(symbol, 0)
    if avg_vol <= 0:
        return 0

    return current_vol / avg_vol
```

### Fix 3: Remove 500K average volume check from simulator

Line 537-538:
```python
avg_vol = self._calculate_avg_volume(symbol)
if avg_vol < SCANNER_CRITERIA['min_avg_volume']:
    return False, {'reason': f"Avg vol {avg_vol:,.0f} < 500K"}
```

Should be removed or changed to 100K

---

## Testing the Fixes

After applying fixes, run:

```bash
# 1. Test with new criteria
python database/sanity_check.py 2026-02-10

# 2. Expected: Should catch 10-15 of the 30 movers (not all, because scanner runs 4am-12pm)
# 3. Expected: Relative volumes should show 5x+, not 0.5x
```

---

## Summary of Changes Required

| File | Issue | Fix |
|------|-------|-----|
| `simulation_engine.py` | Wrong relative vol calc | Use DB method instead of /480 |
| `database/backtest_scanner.py` | CRITERIA wrong | Change min_avg_volume from 500K to 100K |
| `simulation_engine.py` | CRITERIA wrong | Change min_avg_volume from 500K to 100K |
| `simulation_engine.py` | Avg vol filter wrong | Remove or set to 100K |
| `config.py` | CRITERIA wrong | Update defaults |

**Recommendation**: Fix in this order:
1. Update CRITERIA everywhere (5 min)
2. Fix simulation_engine.py relative volume calc (10 min)
3. Re-test sanity_check (5 min)
4. Re-run simulations (30 min)
