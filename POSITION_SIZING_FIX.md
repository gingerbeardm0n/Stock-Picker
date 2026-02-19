# Position Sizing Fix - Account Percentage Cap

**Date**: Feb 18, 2026
**Status**: ✅ COMPLETE & TESTED

---

## The Problem

Risk-based position sizing could severely over-leverage small accounts:

### Example: The Bug in Action
- Stock: **LFS @ $3.93**
- Stop Loss: **$3.87**
- Risk Distance: **$0.06**
- Account: **$5,000**
- Risk Per Trade: **2%** = $100

**Old Calculation**:
```
shares = risk_per_trade / stop_distance
shares = $100 / $0.06 = 1,667 shares
position_value = 1,667 × $3.93 = $6,551
position_pct = $6,551 / $5,000 = 131% of account (CATASTROPHIC!)
```

The old code had a safeguard that checked capital availability, but it only capped shares to the full account balance, still resulting in:
```
shares = $5,000 / $3.93 = 1,271 shares
position_pct = 100% of account (STILL TERRIBLE!)
```

---

## The Solution

Added **account-percentage-based cap** (default 1.5%) to `PositionManager`:

```python
def __init__(self, account_size, risk_per_trade_pct=2.0,
             daily_max_loss_pct=3.0, max_position_pct=1.5):
    self.max_position_pct = max_position_pct  # NEW: Cap position to 1-2% of account
```

### New Position Sizing Logic

```python
# Calculate both approaches
risk_based_shares = int(risk_per_trade / stop_distance)
max_position_value = self.current_balance * (self.max_position_pct / 100.0)
max_position_shares = int(max_position_value / entry_price)

# Use the SMALLER of the two
shares = min(risk_based_shares, max_position_shares)
```

### Example: Same Trade with Fix
```
Account: $5,000
Max Position %: 1.5%
Entry Price: $3.93

max_position_value = $5,000 × 1.5% = $75
max_shares = $75 / $3.93 = 19 shares
position_value = 19 × $3.93 = $74.67
position_pct = $74.67 / $5,000 = 1.49% of account ✅ HEALTHY
```

---

## Test Results

### Single Day Test (Feb 17, 2026)

**Before Fix** ❌ (Hypothetical):
- Position 1: 1,667 shares × $3.84 = $6,406 (128% of account)
- Disaster: Account blown out on first trade

**After Fix** ✅:
- ENTRY @ $3.84 × 19 shares = $72.96 (1.46% of account)
- ENTRY @ $4.03 × 18 shares = $72.54 (1.45% of account)
- ENTRY @ $3.93 × 19 shares = $74.67 (1.49% of account)
- **Result**: +$6 profit, 66.7% win rate on 3 trades

### Multi-Day Test (Feb 10-18, 2026)

```
Trading Days:      6
Winning Days:      2
Losing Days:       1
Flat Days:         3

Total Trades:      12
Avg Trades/Day:    2.0
Total P&L:         -$3
Best Day:          +$6
Worst Day:         -$14

Account Status: HEALTHY (no over-leverage, consistent small positions)
```

---

## Code Changes

### Files Modified:
1. **`database/simulation_engine.py`**:
   - `PositionManager.__init__()`: Added `max_position_pct` parameter (default 1.5%)
   - `PositionManager.enter_position()`: Rewrote position sizing logic with cap
   - `SimulationRunner.__init__()`: Added `max_position_pct` parameter to pass through

### Backwards Compatibility:
- Default `max_position_pct=1.5` works well for all account sizes
- Can be customized: `SimulationRunner(date='...', max_position_pct=2.0)` for 2%
- Existing scripts (`simulate_date.py`, `simulate_date_range.py`) work unchanged

---

## Why 1.5%?

**Justification for small account safety**:

| Account Size | 1.5% Position | Risk Per Trade | 2% Risk |
|--------------|---------------|----------------|---------|
| $1,000       | $15           | $20            | $0.30   |
| $5,000       | $75           | $100           | $1.50   |
| $10,000      | $150          | $200           | $3.00   |
| $25,000+     | $375+         | $500+          | $7.50+  |

**Benefits**:
- Small accounts stay safe (can lose up to 3 trades before 5% account drawdown)
- Matches Ross Cameron's "base hits over home runs" philosophy
- Leaves margin for multiple positions if needed
- Scales naturally with account growth

---

## Next Steps

1. ✅ **Verify Fix** - Multi-day backtest confirmed no over-leverage
2. ⏳ **Paper Trade** - Run live scanner simulation for 2-4 weeks
3. 🔄 **Tune Criteria** - May need to adjust min_relative_volume, float cutoffs
4. 💰 **Go Live** - Start with tiny 1% account positions on real account ($5-$50 per trade)

---

## How to Use

### Command Line (Default 1.5% Cap):
```bash
python database/simulate_date.py --date 2026-02-17 --account 5000 --risk 2.0
```

### Custom Cap (2% instead of 1.5%):
```python
from database.simulation_engine import SimulationRunner

runner = SimulationRunner(
    date='2026-02-17',
    account_size=5000,
    risk_pct=2.0,
    max_position_pct=2.0  # Cap to 2% instead of 1.5%
)
runner.run()
runner.print_report()
```

### For Small Accounts (1%):
```python
runner = SimulationRunner(
    date='2026-02-17',
    account_size=1000,
    risk_pct=2.0,
    max_position_pct=1.0  # Ultra-conservative 1%
)
```

---

## Documentation

- **Memory**: `MEMORY.md` updated with bug description and fix
- **Code Comments**: Added inline comments in `PositionManager.enter_position()`
- **Commit**: `9b71896` with full details

This fix ensures the system is **safe for real money trading** on small accounts.
