# Concept: Behavioral Deviation

**Last updated:** 2026-05-21  
**Source:** RC_STRATEGY_STATISTICS.md (win rates, session counts) + TRANSCRIPT_SUMMARIES_0001-1799 corpus (deviation type breakdown, acct_state correlations)  
**Sample size:** 430 deviation sessions (1,831 trades) vs 1,357 clean sessions (3,430 trades)  
**Win rate WITH deviation:** 49.2% | **Without:** 73.1% | **Delta: -23.9pp**  
**Corpus cross-check:** 332 sessions with non-null `behavioral_deviation` field in chunk files (lower than 430 due to conservative coding in some early files; RC_STRATEGY_STATISTICS.md numbers are authoritative for win rate analysis)

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

**Compounding deviations are catastrophic:** Sessions with 2+ simultaneous deviations have the worst outcomes in the dataset. Each additional deviation multiplies the damage.

**Common compound combinations (from corpus):**

| Compound Type | Sessions | Severity |
|---|---|---|
| revenge-trade + oversize | 12 | Extreme — oversized position on emotional trade |
| revenge-trade + overtrading | 6 | High — multiple revenge entries, not just one |
| oversize + avg-down | 5 | High — too large, then doubles down on loser |
| fomo-entry + oversize | 5 | High — chased AND oversized |
| fomo-entry + revenge-trade | 5 | Extreme — both triggers active simultaneously |
| overtrading + oversize | 4 | High |
| revenge-trade + oversize + broke-rules | 1 | Maximum — all three behavioral failures at once |
| fomo-entry + oversize + revenge-trade | 2 | Maximum — triple compounding |

**Note on positive behavioral coding:** The corpus also documents exemplary sessions in the `behavioral_deviation` field (coded as "exemplary-discipline", "excellent-discipline", "exemplary-crisis-recovery", etc. — ~20 sessions). These represent the opposite extreme: sessions where Ross demonstrated exceptional discipline under difficult conditions. They confirm that the behavioral range runs from -$4,454/trade avg (max-loss-hit + revenge) to documented "exemplary" performance.

---

## Deviation Rate by Account State

**New corpus finding:** Deviation frequency varies dramatically by account state. This is the strongest leading indicator of deviation risk.

| Account State | Sessions | Deviation Sessions | Deviation Rate | Dominant Deviation Type |
|---|---|---|---|---|
| in-drawdown | 208 | 91 | **43.8%** | revenge-trade + oversize (cascade) |
| normal | 549 | 109 | **19.9%** | fomo-entry (single type most common) |
| exceeded-goal | 255 | 37 | **14.5%** | fomo-entry (trying to capitalize on hot day) |
| at-goal | 69 | 10 | **14.5%** | mixed |
| building-cushion | 477 | 54 | **11.3%** | fomo-entry (lowest risk state) |

**Critical insight:** `building-cushion` has the lowest deviation rate (11.3%). This is when Ross is in a comfortable green position mid-session with cushion built — he trades from a position of psychological strength. This is the **optimal trading state** for both performance and discipline.

**Critical insight:** `exceeded-goal` deviations are dominated by **fomo-entry** (11 of 37 sessions), not revenge-trade. When Ross exceeds his daily goal and keeps trading, he takes lower-quality setups out of excitement/FOMO — a different failure mode than the in-drawdown revenge cascade.

**Critical insight:** `in-drawdown` sessions that deviate show **complex multi-type compounds** (revenge + oversize + broke-rules combos). Simple single-type deviations are rare in drawdown — by the time a session goes to drawdown, multiple failures are happening simultaneously.

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
- in-drawdown: 39.7% win rate, -$2,717/trade → worst account state; **43.8% deviation rate** (nearly 1 in 2 sessions)
- Once in drawdown, the temptation to trade larger to recover creates a spiral
- Data confirms the spiral: drawdown → revenge trade → oversizing → deeper drawdown
- `building-cushion` is the SAFEST state: 11.3% deviation rate, 72.1% win rate, +$1,874/trade avg

### 5. Environmental / physical triggers (corpus finding, lower frequency but documented)

| Trigger | Corpus Label | Notes |
|---|---|---|
| Sleep deprivation | `sleep-deprivation-impatience` | Reduced patience → early entries, smaller stops |
| Boredom | `revenge-trade and boredom-driven` | Taking trades not for a setup, but for stimulation |
| Travel / road trip | Multiple sessions (e.g., "van in Canada") | Connectivity issues, physical fatigue → frustration → overtrading |
| Frustration from non-trade issues | `frustration-management` | Tech problems, slow fills → emotional carry into next trade |
| Panic | `panic-trade and hesitation` | Contradictory response — simultaneous panic entry and hesitation exit |

These are low-frequency (1-3 occurrences each) but worth flagging: **jTrader eliminates all of them by being a machine**. However, a human reviewing trade decisions should be aware that non-trading-context stress contaminates trading decisions.

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

Account state is a leading indicator of both performance AND deviation risk:

| Account State | Sessions | Win Rate | Avg Result | Deviation Rate | Risk Level |
|---|---|---|---|---|---|
| in-drawdown | 208 | 39.7% | -$2,717 | **43.8%** | MAXIMUM |
| normal | 549 | 61.6% | +$1,021 | 19.9% | Moderate |
| at-goal | 69 | — | — | 14.5% | Low |
| exceeded-goal | 255 | 77.8% | +$7,064 | 14.5% | Low (but STOP) |
| building-cushion | 477 | 72.1% | +$1,874 | **11.3%** | Lowest |

**The paradox of `exceeded-goal`:** 77.8% win rate looks great, but this is because Ross has STOPPED trading for the day. The *continuation* trades after exceeding the goal (the ones he keeps taking) are what generate fomo-entry deviations. The 14.5% deviation rate applies to sessions that *continue* after exceeding goal.

**`building-cushion` is the ideal state:** Lowest deviation rate (11.3%) + high win rate (72.1%). This is the psychological sweet spot — enough cushion to feel secure, not so much that euphoria sets in. jTrader should try to create and maintain this state by banking early gains.

**`in-drawdown` requires maximum control:** 43.8% deviation rate. Nearly half of all drawdown sessions involve some form of behavioral deviation. This is where the cascade (oversize → revenge → deeper drawdown) begins. See `concept_daily_risk_rules.md` for the circuit-breaker enforcement that prevents this.

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

## size_context = "oversized" as a Standalone Signal

The corpus tracks `size_context` independently from `behavioral_deviation`. **233 sessions** are coded `size_context = "oversized"` (exact match) — a significant standalone dataset. An additional ~13 sessions have oversized-variant labels (oversized-then-correct, emotion-oversized, first-trades-oversized, etc.) bringing total oversizing events to ~246.

Key finding: oversizing is detectable and preventable as its own category, not just as part of a compound behavioral deviation. The fact that 233 sessions have explicit oversizing coded means:
- Oversizing occurs even when other deviations are absent (not always paired with revenge-trade)
- It can be a standalone failure: entering a valid setup but at 2-3x the appropriate size
- jTrader can enforce max_position_pct at the position level before entry — this eliminates oversizing mechanically

**Variants coded in corpus:**
- `oversized-then-correct`: oversized entry, trader recognized and reduced → partial damage control
- `oversized-first-trade-grrr`: explicit regret noted in recap
- `emotion-oversized`: sizing driven by emotion rather than plan
- `first-trades-oversized`: early session oversizing before discipline settles

**jTrader enforcement:** `max_position_pct` cap in PositionManager. Once set, oversizing is structurally impossible regardless of emotional state. See `concept_position_sizing.md`.

---

## Why This Matters More Than Any Pattern

Pattern selection (gap-and-go vs micro-pullback) shifts win rate by ~5-10pp.  
Behavioral deviation shifts win rate by **23.9pp**.

The highest-leverage improvement to jTrader is not finding a better pattern — it's ensuring the Rules 1-5 above are **enforced, not just observed**. Currently `PortfolioManager` logs these events but never fires `halt_new_entries`. This is the most important unimplemented feature in the entire system.

---

## Data Confidence

| Field | Coverage | Confidence |
|-------|----------|------------|
| Deviation vs no-deviation win rate (49.2% vs 73.1%) | 5,261 trades via RC_STRATEGY_STATISTICS.md | Very High |
| Deviation session count (430) | RC_STRATEGY_STATISTICS.md | High |
| Deviation type counts (74 fomo, 56 oversize, etc.) | RC_STRATEGY_STATISTICS.md | High |
| Corpus deviation count (332 non-null) | 19 chunk files, direct grep | High |
| Discrepancy (430 vs 332) | Under-coding in some early chunk files | Explained |
| Deviation rate by acct_state (43.8% in-drawdown etc.) | 332 matched sessions from corpus | High |
| Dominant deviation type by state (revenge vs fomo) | Corpus cross-tabulation | High |
| Compound deviation combinations | Corpus grep, full enumeration | High |
| Account state win rates | RC_STRATEGY_STATISTICS.md | High |
| Max-loss-hit impact (30.9%, -$4,454/trade) | 414 trades | High |
| size_context=oversized (233 sessions exact, ~246 with variants) | 19 chunk files, size_context METADATA extraction | High |
| Environmental triggers (boredom, sleep-dep) | 1-3 occurrences each | Low (rare but documented) |
| Cascade pattern (oversize → revenge → max-loss) | Qualitative across all max_loss files | High |
| Positive behavioral codings (~20 sessions) | Corpus grep | Medium |
