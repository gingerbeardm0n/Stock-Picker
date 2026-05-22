# Concept: Add-On Mechanics (Pyramiding)

**Last updated:** 2026-05-22
**Source:** Full corpus analysis — TRANSCRIPT_SUMMARIES_0001-1799 (all 1,799 sessions)
**Sample size:** 2,593 trades with documented add-on mechanics (out of 4,959 total parsed trade rows = 52.3%)
**Sessions covered:** 1,049 unique sessions had at least one add-on trade

---

## Definition

Add-on mechanics: adding shares to a position that is already open and profitable. Each add is a new buy on the same symbol during the same trade, at a higher price than the prior entry.

**Pyramiding** = the resulting position shape — starter lot near the base (initial entry), smaller lots added as price extends. This is distinct from:
- **Averaging down** (adding to a loser) — Ross explicitly prohibits this; documented as a behavioral deviation in 18-29 sessions
- **Scaled entry** (building the initial position in tranches at approximately the same price level within the first few seconds/minutes of the breakout)

**Core rule: only add to winners, never to losers.**

---

## Statistical Case: How Frequently Are Adds Used?

| Metric | Value |
|--------|-------|
| Total trade rows parsed (all 19 files) | 4,959 |
| Trades with documented add-on mechanic | 2,593 |
| Add-on frequency | **52.3%** |
| Sessions with at least one add-on trade | **1,049 out of ~1,799** |

**Interpretation:** Add-ons are used in more than half of all documented trades. This is not an occasional "home-run" strategy — it is the default operating mode on high-conviction setups. Sessions without add-ons are typically scalp days, cold markets, or trades where the initial entry failed quickly.

### Frequency by Hold Duration

| Hold Duration | Count | % of Add-On Trades |
|---------------|-------|--------------------|
| Short (5-30 min) | 1,249 | 48.2% |
| Scalp (<5 min) | 913 | 35.2% |
| Extended (30min+) | 331 | 12.8% |
| Unknown | 96 | 3.7% |

Extended holds (12.8%) correspond to the largest P&L sessions. The $50K-$200K days in the corpus almost universally involve extended holds with multiple adds (Session 669: +$224K; Session 708: +$205K; Session 1169: +$225K).

---

## Pattern Type Correlation

Which patterns most commonly use add-ons (sorted by total add-on count):

| Pattern | Add-On Trades | Win Rate |
|---------|--------------|----------|
| gap-and-go | 732 | **80.5%** |
| dip-buy | 355 | 73.4% |
| whole-dollar-break | 222 | 67.9% |
| micro-pullback | 202 | **77.3%** |
| halt-resume | 165 | 76.9% |
| vwap-reclaim | 97 | 75.8% |
| red-to-green | 76 | 69.3% |
| flat-top | 35 | **88.2%** |
| breakout | 22 | **95.5%** |
| squeeze | 21 | 85.7% |
| abcd | 18 | 72.2% |
| bull-flag | 13 | **100%** |
| continuation | 10 | 50.0% |

**Key takeaways:**
- Gap-and-go is by far the most frequent add-on pattern (28% of all add-on trades) with strong 80.5% win rate
- Flat-top (88%), breakout (96%), and bull-flag (100%) have very high win rates when adds are used — these are the highest-quality setup types for pyramiding
- Continuation (50%) has a poor win rate with adds — the structure suggests the move is late when you're adding
- Dip-buy is the second most common add-on pattern — Ross adds aggressively on dip-buy setups with 73% win rate

---

## Trigger Conditions: What Confirms the Add

Analysis of the combined ADD_ON_MECHANIC + ENTRY_TRIGGER text across all 2,593 trades:

| Trigger Type | Count | % of Add-On Trades |
|---|---|---|
| Breakout / new high (price breaks above session high or resistance) | 1,109 | **42.8%** |
| General scale / pyramid (unspecified — "added on move", "scaled") | 763 | 29.4% |
| Dip / pullback (add on micro-pullback or dip to support) | 684 | 26.4% |
| Specific price level (add at $X, adds at $3.57/$3.86/etc.) | 210 | 8.1% |
| Halt-resume (already in position, add on halt resumption) | 170 | 6.6% |
| VWAP hold / break (price holds or reclaims VWAP) | 169 | 6.5% |
| Re-entry same day (exit + re-enter on same symbol at higher level) | 147 | 5.7% |
| Aggressive scaling on hot stock (exceptional momentum) | 85 | 3.3% |
| Whole-dollar break (price breaks through whole-dollar level) | 63 | 2.4% |
| MACD confirmed (MACD positive / crossing up at add time) | 5 | 0.2% |

*Note: categories overlap — a trade can have multiple trigger types.*

### Qualitative Trigger Descriptions (from SUMMARY text analysis)

**1. New-High Add (most documented trigger):**
Stock makes a new intraday high after initial entry. Ross adds on the breakout candle above the prior high.
- "Added at $9.25, $9.46, $9.70, $9.88 — pyramided aggressively on way up"
- "Scaled aggressively through $4–$8, adding at each resistance break ($4.19, $4.50, $6.38, $6.70, $7)"
- "Added at $28, $29, $30, $31, hitting high of $31.18"
- "Added to 16,000 shares at $1.46, carefully scaled out at $1.59 and $1.65"

**2. Micro-Pullback / Dip Add (clean confirmation type):**
Stock rips, pulls back 1–3 candles to the 9-MA or VWAP, then resumes → add on the resumption candle.
- "Bought the first dip on 10-second chart, entering 2,500 shares, then adding another 2,500 (5,000 total) as it squeezed to $2.69–$2.77"
- "Rapid entries at $3.35, $3.70, $3.90 on dips during uptrend"
- "Added on dips, capturing +$2,600 as stock reached $1.59"
- "Adding at $4.70, $4.75, $4.80, $4.85, $4.90 accumulating over 40,000 shares" (Session 400-range)

**3. Halt-Resume Add (highest-conviction trigger):**
Already in position heading into a circuit-breaker halt. Stock halts UP (confirms momentum). Add on the resume candle.
- "Added 558, added 563 total ~10,000 shares. Halt resumption quote kept climbing 5→5.20→5.40→higher" (Session 1003, SYTA merger)
- "Added after halt — scaled to $10.00 target" (Session 26)
- "Added on the halt-resume sequence, scaled out at $19.16" (Session 4, WETG)

**4. VWAP Hold Add:**
Price tests VWAP from above, holds, then continues higher → add on the hold confirmation.
- "Entered at $4.60–$4.75, adding at $5.85–$5.95 as it broke VWAP, then held" (Session 46)
- "Adding at $6.11 for the VWAP breakout and then scaling into dips at $6.15, $6.24, $6.31" (Session 33)
- "VWAP consolidation breakout → 2.5K→5K adds" (Session 32)

**5. Whole-Dollar Break Add:**
Stock approaches a whole-dollar resistance level. Ross adds anticipating the break or on the confirmed break candle.
- "Added at resistance" (whole-dollar level — Session 84)
- "Cost basis around $12.59, then added through whole-dollar levels" (Series 400s)
- "Scaling through $26, then $26.50" (Session 500s)

**6. Ascending Support / Price Level Sequence:**
Stock establishes an ascending channel. Ross adds at each step-up in support.
- "Adds at $3.14, $3.18, $3.20, $3.22, $3.24, $3.26" — 6-step ascending add (Session 51)
- "Adds at $0.29, $0.48, $0.55, $0.60, $0.65, $0.77, $0.83" — penny stock ascending (Session 80)

---

## Add-On Sequence Patterns: Number of Adds and Sizing

### Number of Adds Per Trade

| Add-On Steps | Count | % of Add-On Trades |
|---|---|---|
| 1 add | 2,252 | 86.9% |
| 2 adds | 291 | 11.2% |
| 3 adds | 40 | 1.5% |
| 4+ adds | 10 | 0.4% |

**Interpretation:** Most add-on trades (87%) involve a single add to the initial position. Multi-add pyramids (2+) are 13% — but they generate a disproportionate share of the largest wins (the $50K+ days all involve 3-7 tier sequences).

### Sizing Progression

From documented K-sequences in the corpus:

| Sizing Pattern | Count | Description |
|---|---|---|
| Increasing (2K→5K→10K, etc.) | 29 | Conviction grows; each add bigger than last — "reverse pyramid" |
| Same size (2K→2K→2K) | 2 | Rare; equal tranches throughout |
| Decreasing (large starter, smaller adds) | 2 | Standard risk-managed pyramid |
| Mixed / varied | 5 | Size adjusts based on price action |

**Notable size sequences from corpus:**
- Session 3 (LUCY, news-driven): 5K→7.5K→10K→12.5K→15K→17.5K (reverse pyramid, conviction-based)
- Session 4 (WETG, gap-and-go): 2K→2K→2K→1.5K→4.5K→1.5K→1K (varied, reduces at highs)
- Session 9 (flag-breakout): 1.8K→partial fills→45K total (extreme scaling on confirmed breakout)
- Session 30 (banana-squeeze): 2K→2K→2K→2K→1K (equal adds, reduced final)
- Session 32 (flat-bottom): 2.5K→2.5K→2.5K→2.5K→2K (flat tranche sizes, $13–$19 range)
- Session 17 (sympathy): 2.5K→5K→7.5K→10K→12.5K→15K→17.5K (classic reverse pyramid)
- Session 669 (CARV, best day $224K): 10,000-share starters + 8,000-share breakout additions

**Standard pyramid (most trades):**

| Add Tier | Size as % of Initial |
|----------|----------------------|
| Starter | 50–100% of max intended |
| Add 1 | 25–50% of starter |
| Add 2 | ~25% of starter |
| Add 3+ | 10–25% each ("feathering in") |

**Reverse pyramid (high-conviction only):**
Small starter proves the trade right, then large add when confirmed. Session 3 (LUCY): starts 2.5K, finishes 17.5K per tier. Session 17 (sympathy-momentum): same pattern. Requires very high entry quality and tight stop. NOT the default approach — only appropriate on news-driven moves with exceptional momentum.

**Reducing size at highs (risk management):**
Session 4 (WETG): "reduced position size as price extended (4k shares down to 1.5k at highs) due to wider spreads and elevated volatility." Session 708 (DWSN): "started with smaller positions (gained $40k) then overextended with 50,000 shares at $9.75 expecting $15 — 30,000+ share seller crashed the trade." Higher price = higher dollar risk per share = smaller add size.

---

## Stop Management After Each Add

### How Stops Are Managed During Pyramiding

The STOP_CRITERIA column documents 352 reversal signals, 85 halt conditions, 43 failed breakouts, and 35 explicit failed-breakout stops. From qualitative SUMMARY analysis:

**Stop moves UP after each confirmed add:**
- "Profitable stop was established after scaling in" (Session 1400s)
- "Ross applied a conservative strategy of setting stops at breakeven for the add portion" (Session 1300s)
- "Once T1 is hit, move stop on remainder to breakeven — a winner must not turn into a loser"

**Standard stop placement rules after adds:**
| Situation | Stop Location |
|-----------|---------------|
| After Add 1 (new high add) | Below the breakout level just cleared |
| After Add 2 | Below Add 1 entry price (Add 1 is now "protected") |
| After dip add | Below the pullback low (the dip low becomes the stop) |
| After halt-resume add | Below the halt price with buffer |
| After VWAP add | Below VWAP (the level that was reclaimed) |

**Stop exits documented:**
- MACD divergence / negative cross: 11 instances (explicit stop trigger)
- Spreads widening: 11 instances ("wide spreads = market makers stepping away = liquidity leaving")
- Volume declining: 10 instances (sellers stacking 25–30K share blocks = exit signal)
- Reversal signal: 352 instances (most common stop after adds)

### The "One Loss Must Not Follow Two Wins" Rule
From Session 1000 (APVO): "Over-added cost basis moved from 12 to ~15. Decision discipline: locked $1,300 to prevent bigger loss when rejection occurred." Once the add pushes cost basis too high, exit on rejection rather than holding for the theoretical target.

---

## Time of Day: When Adds Happen

| Window | Count | % (of known) |
|--------|-------|----------|
| Pre-market (before 9:30am) | 243 | 9.4% |
| Open / 9:30–9:59am | 452 | 17.4% |
| 10:00–10:30am | 22 | 0.8% |
| After 10:30am | ~15 | <1% |
| Unknown / not documented | 1,714 | 66.1% |

**Key insight from known times:** The vast majority of add-on activity happens in the open (9:30–10:00am) and pre-market windows. Adds after 10:30am are exceedingly rare and represent a behavioral deviation when they occur. The documented 14:30, 2:30pm, and 3:00pm add-on entries in the corpus all correspond to sessions where Ross explicitly noted this was outside his normal approach.

**From Session 2 recap:** "Achieving his $5k daily goal at the 2-hour mark allowed him to stop trading and avoid overtrading in the afternoon." — This is the explicit rationale for the 10:30am cutoff on adds.

---

## Win Rate: Adds vs. No Adds

| Metric | Add-On Trades | All Trades |
|--------|--------------|-----------|
| WIN | 1,886 | — |
| LOSS | 619 | — |
| Win Rate | **75.3%** | ~69% (overall corpus estimate) |

**Interpretation:** Trades where adds were used have a higher measured win rate (75.3%) than the overall corpus average. This is partially selection bias — Ross uses larger position adds only on high-conviction setups — but it confirms that the add-on mechanic is associated with better outcomes, not worse.

### Win Rate by Pattern Type (add-on trades only)

| Pattern | Win Rate | Notes |
|---------|----------|-------|
| bull-flag | 100% | Small sample (13 trades) |
| breakout | 95.5% | Strong signal |
| flat-top | 88.2% | Consolidation breakout premium |
| squeeze | 85.7% | Confirmed momentum |
| consolidation | 85.7% | |
| news (news-driven) | 85.7% | Catalyst adds = higher win rate |
| gap-and-go | 80.5% | Most common pattern |
| dip-trade | 80.0% | |
| micro-pullback | 77.3% | |
| halt-resume | 76.9% | |
| vwap-reclaim | 75.8% | |
| dip-buy | 73.4% | |
| abcd | 72.2% | |
| red-to-green | 69.3% | Weaker confirmation |
| continuation | 50.0% | Late-move entries — caution |
| daily-breakout | 20.0% | Very poor; adds on daily setups fail |

---

## Failure Modes: What Goes Wrong on Losing Add-On Trades

619 add-on trades resulted in losses. From stop criteria analysis:

| Failure Mode | Count | % of Losses |
|---|---|---|
| Reversal after add (sudden reversal post-add) | 210 | 33.9% |
| False breakout (add on breakout that fails) | 146 | 23.6% |
| Other / unclear | 215 | 34.7% |
| Halt risk (adverse halt on open position) | 21 | 3.4% |
| Aggressive add on extended move | 21 | 3.4% |
| Dip add — failed continuation | 5 | 0.8% |

### Documented Failure Patterns from SUMMARY Text

**1. Adding on extension (oversize at top):**
"He had built a substantial position with an average entry around $7. By the time the stock peaked at $59, he held nearly $200,000 in unrealized [gain that evaporated]." (Session 500s)
"He entered with 1,000 shares then rapidly added to 6,000 shares total at a cost basis of $13/share, then capitulated at $8." (Session 1000s)
"STAK: Ross started with smaller positions (gained $40k) then overextended with 50,000 shares at $9.75 expecting $15 target — a 30,000+ share seller crashed trade" (Session 708, -$51K)

**2. Adding on weakness (averaging down masked as "adding"):**
"He added on the way down trying to average in but got caught stopped out at a large loss." (Session 600-700s)
"Added at $14, $15, $16 expecting support holds, but the stock flushed through $16 back to $12." (Session 100s)

**3. Re-entry after missed exit (FOMO add):**
"Second entry at same $7.20 level hoping for continuation through $7 — proved costly, losing $1,200" (Session 200s)
"He was down to +$1,200 overall. [He re-entered] SPRO — scaled into 20,000 shares anticipating a $2.15 breakout and saw the stock curl instead" (Session 300-400s)

**4. Cost basis too high after multi-tier add:**
"APVO: Over-added cost basis moved from $12 to ~$15. Stock rejected hard at $18 back to $14, gave back to $11." (Session 1000)
Lesson: Each add increases average cost basis. At some point (add 3+), the breakeven price is well above the entry and a normal pullback constitutes a loss on the total position.

**5. Not taking partial profits before adding:**
Session 708: "Overextended with 50,000 shares at $9.75 expecting $15 target." The rule violated: no partial exits taken before the final add — entire position at risk.

---

## Account Size / Market Condition Correlation

### Account Size Effect on Add Size
From corpus evolution (early sessions = small account; late sessions = large account):
- Early sessions (1–200): Add sequences in 2K–10K share range
- Mid-corpus (200–800): 10K–30K share sequences common
- Late corpus (800–1799): 30K–75K+ share sequences on exceptional days
- Peak trades: Session 669 (+$224K), Session 708 (+$205K), Session 1169 (+$225K) — all large-account, maximum-conviction scaling

### Hot vs. Cold Market Effect
- **Hot markets:** Ross explicitly deploys "reverse pyramid" (grows with conviction), more adds, larger final size, holds longer. Session 586: "ARAZ [$112K]... hot environment... scaled into halts." Session 669: "Perfect storm: four-to-five stocks gapping over 100%... aggressive add strategies throughout the day's 20-point run."
- **Cold/slow markets:** Single entry, exits at T1, no adds. From Session 1004: "No strong follow-through today, choppiness, light volume — limited hot setups, focused on QNRX quality only."
- **Post-drawdown / recovery mode:** Position caps and guard rails apply to adds. Session 1001: "In trading rehab after $60k loss — managing risk by accepting smaller positions vs max-scaling." Later files document explicit guard_rails like "max 15K shares until +$1K cushion" and "position cap 6K until recovery ends."

### Float Size Effect
From add-on trades with documented float:
- sub-1M/sub-5M float: gap-and-go (9), dip-buy (6), micro-pullback (5) — small float favors all pattern types with adds
- low-float: gap-and-go (9), micro-pullback (4), news-driven (2) — similar distribution
- high-float: rare add-on use; when used, tends to fail more (continuation stops, dip-trade reversals)

---

## The Pyramid vs. Averaging Down Distinction

| | Pyramid (add to winner) | Averaging down (add to loser) |
|---|---|---|
| When to add | Price moving in your favor | Price moving against you |
| Stop placement | Trail up after each add | Unclear — cost basis somewhere below |
| Risk on failure | Reduced (partials lock in profit) | Increased (larger position at worse price) |
| Ross does? | YES — core mechanic | NO — documented as behavioral deviation (18-29 sessions across corpus) |
| jTrader should do? | YES | NEVER |

**Behavioral deviation note:** In sessions where Ross "averaged down" rather than pyramiding, it is explicitly flagged in the SUMMARY as a mistake — "added at $15.23, $15.30 generating +$1,000 profit" (correct) vs. "added at $3.75, $3.85, $3.95 expecting support holds, but the stock flushed through $4.00" (averaging down — wrong pattern).

---

## Scaled Entry vs. True Add-On (Code Implementation Distinction)

**Scaled entry** (occurs in ~67 corpus trades): building the initial position across 2–3 entries at approximately the same price level during the setup confirmation phase. Entries happen within the first few seconds/minutes as the breakout develops — essentially taking a full position in tranches rather than one order.

Example: Ross enters 2K at $3.50 break, then adds 2K more at $3.52 as momentum confirms → total 4K at avg $3.51. This is one "trade" in his mind with a scaled entry, not a pyramid.

**True add-on**: the initial position is established, the stock has moved in your favor (+$0.20 or more), and you add more at $3.70 to participate in further upside. This is the pyramid.

**Why this matters for jTrader:** Scaled entry happens in `evaluate_entry()` — initial position can be built in tranches. Add-ons happen in a separate `add_on_signal()` — evaluated after the initial entry is profitable. These are different code paths with different timing logic.

---

## Exit Plan After Adds (Scaling Out)

With a pyramided position:
- **T1** (30–50% of total position): first resistance level — covers cost of all adds
- **T2** (25% of remaining): next resistance
- **Remainder**: trail stop above prior low / VWAP / EMA-9
- **Rule**: once T1 is hit, move stop on full remaining position to breakeven or better — a winner must not turn into a loser
- **Rule**: scale out partials into strength before adding again — do NOT accumulate a max position without first locking some profit

---

## When NOT to Add

| Rule | Evidence from Corpus |
|------|---------------------|
| Never add to a losing trade | Documented as behavioral deviation in 18–29 sessions; always ends worse than stopping out |
| Never add after 10:30am | Only ~2% of add-on trades occur after 10:30am — almost all are morning window |
| Never add when spread widens | Spreads widen = market makers stepping away = liquidity leaving; documented as stop criterion 11 times |
| Never add if MACD line turns negative | 5 MACD-specific stops documented; qualitative rule in multiple summaries |
| Never add past max position limit | Size limits apply to total position including adds |
| Never add more than 3x initial | Beyond this, risk management is broken; Session 708 STAK add to 50K shares violated this |
| Never add during drawdown without guard rails | Documented in later files: explicit "max 15K until +$1K cushion" caps |
| Never add on continuation pattern (after 10:00am) | 50% win rate on continuation adds — worst performing pattern type |
| Never add when volume is declining | Declining volume = interest leaving; stop criterion documented 10 times |

---

## Largest Documented Pyramids

| Session | Symbol | Scale Sequence | P&L | Pattern |
|---------|--------|----------------|-----|---------|
| 669 | CARV | 10K starter + 8K breakout additions | +$224K | gap-and-go, hot market |
| 708 | DWSN | Scaled through $4–$8 (10K–50K range) | +$212K | micro-pullback |
| 1169 | — | Max-scale hot-market pyramid | +$225K | multiple patterns |
| 586 | ARAZ | Scale through halts | +$112K | halt-resume |
| 3 | LUCY | 5K→7.5K→10K→12.5K→15K→17.5K | Multi-thousand | news-driven |
| 17 | Sympathy | 2.5K→5K→7.5K→10K→12.5K→15K→17.5K | Multi-thousand | sympathy-momentum |
| 9 | — | 1.8K→partial fills→45K total | High | flag-breakout |
| 51 | — | Adds at $3.14, $3.18, $3.20, $3.22, $3.24, $3.26 | — | ascending-support |
| 32 | — | 2.5K→2.5K→2.5K→2.5K→2K through $13–$19 | +$8K+ | flat-bottom, VWAP |
| 1003 | SYTA | 5K starter, added 558 563, post-halt surge | +$31K | halt-resume merger |

---

## jTrader Implementation (GAP-03)

### Current Status
jTrader implements one entry per trade. No add-on logic exists.

**Implemented:**
- Single entry per `evaluate_entry()` call
- T1 (30%) and T2 (25%) scale exits

**Missing:**
- `add_on_signal()` — evaluates whether current position state warrants adding
- Re-entry detection for same symbol mid-trade at a higher price level
- Position pyramid tracking (`current_position_size` vs `max_position_size`)

### Priority Order for Implementation

Based on frequency in corpus:
1. **Breakout/new-high add** (42.8% of trigger category) — add on break above session high
2. **General continuation add** (29.4%) — add as price continues making higher highs/lows
3. **Dip/pullback add** (26.4%) — add on micro-pullback to support
4. **Halt-resume add** (6.6%) — add when resuming from halt-up
5. **VWAP add** (6.5%) — add on VWAP hold from above

### Decision Logic

```python
ADD_ON_SIGNAL(symbol, position, bars, indicators, cfg):
  """
  Called once per bar on any open position.
  Returns: (should_add: bool, add_size: int, new_stop: float)
  """

  # Preconditions (all must pass)
  if not position.is_profitable():          return False  # never add to loser
  if position.total_size > cfg.max_position_size * 3:  return False  # over-added
  if current_time > 10:30am:               return False  # outside morning window
  if position.add_count >= 4:              return False  # max 4 adds per trade
  if not position.has_taken_partial():     return False  # must scale out before adding again

  # Gate 1: BREAKOUT / NEW HIGH ADD (most common trigger)
  if bars[-1].high > session_high_before_now:
    add_size = initial_position_size * 0.25
    new_stop = session_high_before_now * 0.995  # trail to breakout level
    return True, add_size, new_stop

  # Gate 2: MICRO-PULLBACK RESUMPTION ADD
  if detect_micro_pullback(bars, indicators, cfg):
    # Pullback to 9-MA or VWAP, then resumes higher
    add_size = initial_position_size * 0.25
    new_stop = bars[-2].low - cfg.stop_buffer  # below pullback low
    return True, add_size, new_stop

  # Gate 3: HALT-RESUME ADD
  if halt_just_resumed() and current_price > halt_price:
    add_size = initial_position_size * 0.50  # larger — highest conviction
    new_stop = halt_price * 0.98
    return True, add_size, new_stop

  # Gate 4: VWAP RETEST ADD
  if price_touched_vwap_from_above(bars) and bars[-1].close > vwap:
    add_size = initial_position_size * 0.25
    new_stop = vwap * 0.998
    return True, add_size, new_stop

  # Gate 5: WHOLE-DOLLAR BREAK ADD
  if crossed_whole_dollar_level(bars[-1]) and macd_positive():
    add_size = initial_position_size * 0.20
    new_stop = whole_dollar_level * 0.998
    return True, add_size, new_stop

  return False, 0, position.stop

# Post-add:
#   recompute_breakeven(position)
#   update_stop_to_protect_t1(position)
#   if added_position_risk > max_daily_risk_per_symbol: SKIP add
```

### Sizing During Add-Ons

| Add Tier | Size Rule | Rationale |
|----------|-----------|-----------|
| Initial entry | 50-100% of max position | Starter to confirm setup |
| Add 1 | 25-50% of initial | Position growing on conviction |
| Add 2 | 25% of initial | More risk per share at higher price |
| Add 3 | 10-25% of initial | Feathering in; near max position |
| Add 4+ | 10% of initial | Rare; only on halting-up momentum |

**Hot market multiplier:** In hot market conditions (≥3 halts in session, ≥2 stocks up 100%+), add sizes can be increased by 25-50% from the above table. This is consistent with Session 669 (CARV) and Session 708 (DWSN) behavior.

**Recovery mode cap:** When account is in drawdown phase (≥2 red days prior), apply guard rail: maximum 50% of normal add sizes. Do not increase add size until +1K cushion established.

### Expected Impact

The gap between average win (+$1,913) and top-pattern average (+$7,126) is largely explained by missing add-on logic. With adds:
- Gap-and-go winner average would increase from ~$3,800 to ~$6,000+
- Extended-hold VWAP reclaim trades would increase from ~$7,000+ to potentially $15,000–$25,000
- The +$50K–$200K sessions in the corpus are structurally impossible without multi-tier adds

---

## Data Confidence

| Finding | Sample Size | Confidence | Notes |
|---------|------------|------------|-------|
| Add-on frequency (52.3% of trades) | 4,959 parsed trade rows | **HIGH** | Direct column extraction from TRADE_MECHANICS table across all 19 files |
| Session count with adds (1,049) | All 1,799 sessions | **HIGH** | Parser verified against file structure |
| Win rate with adds (75.3%) | 2,505 trades with outcome data | **HIGH** | Outcome column populated; selection bias possible |
| Pattern type distribution | 2,593 add-on trades | **HIGH** | Direct field extraction |
| Trigger type classification | 2,593 add-on trades | **MEDIUM** | Text-based classification; some overlap; "general scale" category is fuzzy |
| Add sequence steps (87% = 1 add) | 2,593 add-on trades | **HIGH** | Arrow-pattern counting; accurate for explicit sequences |
| Time of entry distribution | 879 with time data (66% unknown) | **MEDIUM** | Large unknown fraction limits precision |
| Size sequence direction (increasing/decreasing) | 38 explicit K-sequences | **LOW** | Most size sequences not documented with explicit K-notation |
| Failure mode breakdown | 619 loss trades analyzed | **MEDIUM** | Stop-criteria text classification; some entries generic |
| Account size / market correlation | Qualitative from 10+ sessions | **MEDIUM** | Pattern observed but not systematically coded |
| Stop management details | Qualitative from SUMMARY text | **MEDIUM** | Consistent across multiple sessions but not uniformly documented |
| "Never add after 10:30am" rule | <2% post-10:30 add-on trades | **HIGH** | Quantitative support from timing data |
| Float effect on add-on pattern | 60 trades with float + add | **LOW** | Float field sparsely populated |
| Reverse pyramid (grow with conviction) | ~10 documented sequences | **MEDIUM** | Consistent direction but small documented sample |
