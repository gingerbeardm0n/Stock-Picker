# Concept: Add-On Mechanics (Pyramiding)

**Last updated:** 2026-05-07  
**Source:** concept_pattern_playbook.md (FILES 0004, 0006, 0017, 0019, 0026, 0027, 0348); RC_STRATEGY_STATISTICS.md  
**Sample size:** 5,010 trades (playbook basis)  
**Relevance:** Explains the gap between average win (+$1,913) and top-pattern wins (+$3,791–$7,126)

---

## Definition

Add-on mechanics: adding to a position that is already open and profitable. Each add is a new buy on the same symbol during the same trade, at a higher price than the prior entry.

Pyramiding = the resulting position shape — largest lot near the base (initial entry), smaller lots added as price extends. This is distinct from averaging down (adding to a loser). Ross's most profitable trades are multi-add pyramids, not single entries.

**Core rule: only add to winners.**

---

## Statistical Case

| Pattern | Avg win | Likely cause of size |
|---------|---------|----------------------|
| All trades (avg) | +$1,913 | Includes single-entry trades |
| Gap-and-go | +$3,791 | Multi-add during stair-step |
| VWAP reclaim | +$7,126 | Extended hold with adds on retests |
| Dip buy pyramid (FILE 0017) | Multi-thousand+ | 7-tier scale-in |

The $1,913→$7,126 gap is explained primarily by position sizing via adds, not by pattern edge alone.

---

## The Four Add-On Triggers

### 1. Break of New High

Price makes a new high of session after initial entry → add on the break.

- Add 1: price breaks above first new high
- Add 2: price breaks above next resistance
- Stop: trail to below each successive breakout level
- Example (FILE 0004, gap-and-go): 2K→2K→2K→1.5K→4.5K→1.5K as stock stair-stepped up

### 2. Micro-Pullback Resumption

Stock rips, pulls back 1-3 candles, then resumes → add on resumption candle.

- Initial entry: at the breakout
- Add: first micro-pullback re-entry
- Multiple adds: each successive micro-pullback in the stair-step
- Example (FILE 0027): rapid adds at $3.35, $3.70, $3.90 on successive dips during uptrend
- Example (FILE 0006, dip buy): 3K→6K→9K at $3.50 break

### 3. Post-Halt Resume Add

Already in position pre-halt → add on halt resume if direction confirmed.

- Highest-conviction add: halt confirms extreme momentum
- Add size: up to 50% of initial (larger than other triggers)
- Stop: halt price minus buffer
- Example (FILE 0026, target $10): multiple adds during halt-resume sequence
- Example (FILE 0019, VWAP + halt combination): extended hold with adds

### 4. VWAP Retest Add

Stock dips to VWAP from above, reclaims it → add on successful retest.

- Initial entry: VWAP reclaim breakout candle
- Add: first confirmed hold of VWAP from above (former resistance = support)
- Stop for add: close back below VWAP
- Example (FILE 0348, 180% gap): VWAP reclaim add, target $6.18

---

## Pyramid vs. Averaging Down

| | Pyramid (add to winner) | Averaging down (add to loser) |
|---|---|---|
| When to add | Price moving in your favor | Price moving against you |
| Stop placement | Trail up after each add | Unclear — cost basis somewhere below |
| Risk on failure | Reduced (partials lock in profit) | Increased (larger position at worse price) |
| Ross does? | YES — core mechanic | NO — rule deviation (recorded 18-29 sessions) |
| jTrader should do? | YES | NEVER |

---

## Position Sizing During Adds

Standard pyramid (most trades):

| Add tier | Size as % of initial |
|----------|----------------------|
| Starter | 50-100% of max intended |
| Add 1 | 25-50% of starter |
| Add 2 | ~25% of starter |
| Add 3+ | 10-25% each ("feathering in") |

Rationale for shrinking add sizes: higher price = larger dollar risk per share; less room before a normal pullback hits the stop; total dollar risk per trade must stay constant, so share count must decrease as price extends.

**Reverse pyramid (high-conviction trades only):**

Small starter to prove the trade right, then large add when confirmed. Example (FILE 0017, dip buy): adds were 2.5K, 5K, 7.5K, 10K, 12.5K, 15K, 17.5K — each add larger than the last. This approach requires very high entry quality and a tight stop. Not the default approach.

---

## When NOT to Add

| Rule | Reason |
|------|--------|
| Never add to a losing trade | Averaging down destroys P&L — documented across 29 sessions |
| Never add after 10:30am | Morning momentum window has closed; adds in dead zone create oversized losing positions |
| Never add when spread widens | Wide spread = market makers stepping away = liquidity leaving |
| Never add if MACD line turns negative | Front-side requirement extends to add-on decisions |
| Never add past max position limit | Size limits apply to total position, not just initial entry |
| Never add more than 3x initial | Beyond this, risk management is broken |

---

## Exit Plan After Adds

With a pyramided position:

- **T1** (30-50% of total): first resistance — covers cost of all adds
- **T2** (25% of remaining): next resistance
- **Remainder**: trail stop above prior low / VWAP / EMA-9
- **Rule**: once T1 is hit, move stop on remainder to breakeven or better — a winner must not turn into a loser

---

## jTrader Current Status

jTrader implements one entry per trade. No add-on logic exists.

**Implemented:**
- Single entry per `evaluate_entry()` call
- T1 (30%) and T2 (25%) scale exits

**Missing:**
- `add_on_signal()` — evaluates whether current position state warrants adding
- Re-entry detection for same symbol mid-trade at a higher price level
- Position pyramid tracking (`current_position_size` vs `max_position_size`)

**Expected impact:** The gap between average win (+$1,913) and top-pattern average (+$7,126) is largely explained by missing add-on logic. With adds, the best trades would generate 2-4x current returns.

---

## jTrader Decision Rules

```
ADD_ON_MECHANIC (not yet implemented):

  Preconditions:
    - Currently in position on symbol (open, not at stop)
    - Trade is profitable: current_price > entry_price
    - current_position_size < initial_position_size * 3  (don't over-add)
    - time < 10:30am ET (morning momentum window only)
    - macd_line > 0 if available (front side still active)

  Trigger evaluation (in order):

    1. NEW_HIGH_ADD:
       IF current_bar['high'] > session_high_before_this_bar:
         add_size = initial_position_size * 0.25
         stop = current_position_stop  (trail up to breakout level)
         → ADD

    2. MICRO_PULLBACK_ADD:
       IF detect_micro_pullback(bars, indicators, cfg):
         add_size = initial_position_size * 0.25
         stop = pullback_low - buffer
         → ADD

    3. HALT_RESUME_ADD:
       IF resume_detected AND current_price > halt_price:
         add_size = initial_position_size * 0.50
         stop = halt_price - buffer
         → ADD

    4. VWAP_RETEST_ADD:
       IF price_touched_vwap_from_above AND current_bar['close'] > vwap:
         add_size = initial_position_size * 0.25
         stop = vwap - buffer
         → ADD

  IF none trigger → hold current position, do not add

  Post-add:
    - Recompute breakeven price for total position
    - Update trailing stop to protect T1 level on total position
    - IF added position would push total risk > max_daily_risk_per_symbol → SKIP add
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---------|--------|------------|
| Add-on examples from playbook | 5,010 trades | High |
| Avg win correlation with pattern quality | 5,261 trades | High |
| Pyramid vs averaging down distinction | Qualitative from recaps | High |
| Specific add-on sizing (25-50% of starter) | Qualitative | Medium |
| Expected return impact of add-ons | Inferred | Low (no direct measurement) |

---

**Last updated:** 2026-05-07  
**Source:** concept_pattern_playbook.md (FILES 0004, 0006, 0017, 0019, 0026, 0027, 0348); RC_STRATEGY_STATISTICS.md
