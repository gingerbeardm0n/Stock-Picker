# Concept: Behavioral Deviation

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md — 1,787 sessions, 5,261 trades  
**Sample size:** 430 deviation sessions (1,831 trades) vs 1,357 clean sessions (3,430 trades)  
**Win rate WITH deviation:** 49.2% | **Without:** 73.1% | **Delta: -23.9pp**

---

## Definition

Behavioral deviation is any instance where Ross Cameron departs from his own pre-defined rules during a trading session. It includes FOMO entries, oversizing, revenge trading, averaging down, and late exits.

This is the single most statistically significant finding in the 1,787-session dataset. A 23.9pp win rate gap means a deviating Ross Cameron is a **net-losing trader** (49.2%, barely coin-flip) while a disciplined Ross Cameron is one of the best momentum traders in existence (73.1%).

The automation argument in one number: **Ross wins 73.1% when following rules. Ross wins 49.2% when emotional.**

---

## Statistical Case

| Category | Sessions | Trades | Win Rate | Avg Result | Total P&L |
|----------|----------|--------|----------|------------|-----------|
| With behavioral deviation | 430 | 1,831 | **49.2%** | **+$43** | +$73,820 |
| Without behavioral deviation | 1,357 | 3,430 | **73.1%** | **+$2,905** | +$9,490,855 |

Key observations:
- Deviation sessions: 49.2% win rate, +$43/trade avg → **effectively breakeven with fees destroying net P&L**
- Clean sessions: 73.1% win rate, +$2,905/trade avg → **dominant positive expectancy**
- 430 deviation sessions represent 24% of all trading days — roughly 1 in 4 days Ross deviated
- The $9.49M vs $73K P&L split shows 99.2% of total profits came from non-deviation sessions

---

## Deviation Type Breakdown

| Deviation Type | Sessions | Notes |
|----------------|----------|-------|
| fomo-entry | 74 | Chasing moves already in progress |
| oversize | 56 | Too many shares relative to account / risk rules |
| overtrading | 38 | Too many trades, not waiting for A+ setups |
| revenge-trade | 29 | Trading to recover a loss, not for a valid setup |
| avg-down | 18 | Adding to a losing position |
| late-exit | 18 | Holding past the stop or target |
| revenge-trade + oversize | 12 | Compound deviation — worst outcomes |
| broke-rules (general) | 11 | Explicit rule violation noted in recap |

**Compounding deviations are catastrophic:** Sessions with 2+ simultaneous deviations (revenge + oversize, FOMO + oversize + broke-rules) have the worst outcomes in the dataset. Each additional deviation multiplies the damage.

---

## Deviation Trigger Conditions

From session analysis, deviations cluster around specific conditions:

### 1. After a loss (revenge trading)
- Ross takes a loss → emotional state changes → next trade is oversized or FOMO
- Most common cascade: STOP_HIT → revenge-trade → oversize → second loss → max-loss-hit
- Data: max-loss-hit sessions have 30.9% win rate, -$4,454/trade avg (section 10 of stats)

### 2. After a big win (euphoria / FOMO)
- Ross has a good morning → tries to "keep the momentum going" → takes setups below his threshold
- Symptom: trade count increases sharply after a big win
- Data: exceeded-goal account state has 77.8% win rate — but this is when Ross STOPS, not when he keeps going

### 3. Market session quality mismatch
- Cold market day → Ross tries to force trades that don't meet criteria
- Cold market: 53.9% win rate, -$63/trade (vs hot: 71.9%, +$3,516)
- Forcing trades on cold days is the most common overtrading trigger

### 4. Account state deterioration
- in-drawdown: 39.7% win rate, -$2,717/trade → worst account state
- Once in drawdown, the temptation to trade larger to recover creates a spiral
- Data confirms the spiral: drawdown → revenge trade → oversizing → deeper drawdown

---

## The Deviation Prevention System

jTrader's entire existence is justified by this data. An algorithm cannot:
- Feel FOMO
- Take revenge trades
- Chase setups out of euphoria
- Average down emotionally

But code CAN replicate the deviations if not designed carefully:
- **FOMO equivalent:** Entering when `pct_change` just barely meets threshold on no news (same as chasing)
- **Oversize equivalent:** `max_position_pct` bug in old PositionManager (1.5% vs 20%)
- **Overtrading equivalent:** No `max_trades_per_day` limit — system enters every qualifying signal
- **Revenge trade equivalent:** Re-entering a symbol immediately after stop-hit (TIME_DECAY re-entry bug, already fixed)

---

## Hardcoded Prevention Rules

These rules structurally prevent the most common deviations:

### Rule 1: Daily Max Loss Halt (prevents revenge trading)
```
IF daily_pnl <= -max_loss_limit:
    halt_new_entries = True
    log("MAX_LOSS_HIT — no new entries today")
```
Data: 30.9% win rate after max-loss hit. Any trade after this point is statistically expected to lose.

### Rule 2: Green-to-Red Halt (prevents revenge trading on good days)
```
IF daily_pnl was > 0 AND daily_pnl drops to <= 0:
    halt_new_entries = True  
    log("GREEN_TO_RED — protecting gains")
```
Going green-to-red triggers the same emotional response as a loss. Data: sessions that go G2R and continue trading have deviation signatures.

### Rule 3: Give-Back-Half Halt (prevents euphoria continuation)
```
IF daily_peak_pnl > 0 AND daily_pnl < daily_peak_pnl * 0.5:
    halt_new_entries = True
    log("GIVE_BACK_HALF — protecting $X of gains")
```
Ross: "If I give back 50%, that's a hard stop." Keeps big green days green.

### Rule 4: Max Trades Per Day (prevents overtrading)
```
IF trades_today >= max_trades_per_day:  # suggest: 3-5
    halt_new_entries = True
    log("MAX_TRADES_HIT — session complete")
```
Overtrading is 3rd most common deviation. A hard cap prevents it entirely.

### Rule 5: No Re-entry After Stop on Same Symbol (prevents averaging down / revenge)
```
IF symbol in stopped_out_today:
    skip entry
```
Averaging down and revenge trading on same symbol are related. One rule blocks both.

---

## Account State Awareness

Account state is a leading indicator of deviation risk:

| Account State | Win Rate | Avg Result | Risk Level |
|---------------|----------|------------|------------|
| in-drawdown | 39.7% | -$2,717 | 🔴 MAXIMUM |
| exceeded-goal (stop!) | 77.8% | +$7,064 | 🟢 STOP TRADING |
| building-cushion | 72.1% | +$1,874 | 🟢 Optimal state |
| normal | 61.6% | +$1,021 | 🟡 Proceed cautiously |

The 77.8% / +$7,064 for `exceeded-goal` is paradoxical — it looks great, but this is because Ross has STOPPED trading for the day. The *remaining* trades after exceeding the goal (the ones he continues to take) are what cause the give-back problem.

**jTrader rule:** When `exceeded-goal` is detected (daily P&L > daily_goal), apply give-back-half rule immediately. Don't continue trading unless setups are A+.

---

## jTrader Decision Rules

```
BEHAVIORAL_DEVIATION_PREVENTION:

  # Evaluated at the start of each potential entry
  
  Check 1: Max loss halt
    IF daily_pnl <= -cfg.max_loss_limit:
      BLOCK entry → "MAX_LOSS_HIT"
  
  Check 2: Green-to-red halt
    IF session_peak_pnl > 0 AND daily_pnl <= 0:
      BLOCK entry → "GREEN_TO_RED"
  
  Check 3: Give-back-half halt
    IF session_peak_pnl > 0 AND daily_pnl < session_peak_pnl * 0.5:
      BLOCK entry → "GIVE_BACK_HALF"
  
  Check 4: Max trades halt
    IF trades_today >= cfg.max_trades_per_day:
      BLOCK entry → "MAX_TRADES"
  
  Check 5: Stopped-out symbol
    IF symbol in stopped_out_symbols_today:
      BLOCK entry → "SYMBOL_BLOCKED_AFTER_STOP"
  
  Check 6: Market temperature gate
    IF market_temp == "cold":
      IF setup_quality < A_PLUS:
        BLOCK entry → "COLD_MARKET_BELOW_THRESHOLD"
  
  # If all checks pass → proceed to pattern detection
  ALLOW entry
```

---

## Why This Matters More Than Any Pattern

Pattern selection (gap-and-go vs micro-pullback) shifts win rate by ~5-10pp.  
Behavioral deviation shifts win rate by **23.9pp**.

The highest-leverage improvement to jTrader is not finding a better pattern — it's ensuring the Rules 1-5 above are **enforced, not just observed**. Currently `PortfolioManager` logs these events but never fires `halt_new_entries`. This is the most important unimplemented feature in the entire system.

---

## Data Confidence

| Field | Coverage | Confidence |
|-------|----------|------------|
| Deviation vs no-deviation win rate | 5,261 trades | Very High |
| Deviation type counts | 430 sessions | High |
| Account state win rates | Complete | High |
| Max-loss-hit impact | 414 trades | High |
| Cascade patterns | Qualitative | Medium |
