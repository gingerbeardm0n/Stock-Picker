# Pattern Playbook

**Last updated:** 2026-05-06
**Source:** Pass 1 enrichment, FILES 0001–1799
**Total trades in sample:** 5,010

---

## Quick Reference Table

| Pattern            |  n   | Win%  | Scalp% | Short% | Extended% | MACD Rel | Primary Float | Primary Time Window |
|--------------------|------|-------|--------|--------|-----------|----------|---------------|---------------------|
| gap-and-go         | 1177 | **69%** | 37.6%  | 48.2%  | 9.7%      | 3.7%     | any           | premarket → 9:30–10:30 |
| dip-buy            |  712 | 63%   | 35.8%  | 46.8%  | 6.2%      | 4.4%     | any           | 9:30–11:00 |
| whole-dollar-break |  428 | 59%   | 50.9%  | 39.0%  | 6.3%      | 2.3%     | low/mid       | 9:30–10:30 |
| micro-pullback     |  387 | **70%** | 43.7%  | 36.7%  | 9.3%      | 4.7%     | low-float     | 9:30–10:30 |
| halt-resume        |  319 | 67%   | 35.7%  | 46.4%  | 7.5%      | 2.8%     | low/mid       | any (halt-driven) |
| vwap-reclaim       |  153 | **75%** | 25.5%  | 43.8%  | 11.8%     | 2.6%     | any           | 9:30–11:00 |
| red-to-green       |  143 | 65%   | 51.7%  | 40.6%  | 3.5%      | 2.1%     | any           | 9:30–10:00 |
| flat-top           |   82 | 64%   | 54.9%  | 37.8%  | 7.3%      | 1.2%     | low/mid       | premarket or early market |
| abcd               |   26 | —     | 15.4%  | 73.1%  | 11.5%     | 0.0%     | low-float     | 9:30–10:30 |
| bull-flag          |   26 | —     | 34.6%  | 38.5%  | 11.5%     | 0.0%     | any           | 9:30–10:30 |

**Win% source:** OUTCOME column from TRADES tables, 6,722 total outcomes parsed. Win/loss only — breakeven (113) excluded.  
**Key ranking:** vwap-reclaim 75% > micro-pullback 70% > gap-and-go 69% > halt-resume 67% > dip-buy 63% > whole-dollar-break 59%  
**Hold duration:** scalp = <5 min; short = 5–30 min; extended = 30 min+  
**MACD Rel** = % of trades where MACD positive was recorded (floor estimate — many trades have unknown MACD state).

---

## Pattern Sections

---

### 1. Gap-and-Go

**n = 1,177 | Scalp 37.6% / Short 48.2% / Extended 9.7% | MACD relevance 3.7%**

**Definition:** A stock gaps up significantly premarket on news or catalyst and continues higher after the open without filling the gap. The move is driven by momentum buyers piling in at the open.

**Setup criteria:**
- Gap of at least 10–20% premarket (examples in sample: 40%, 57%, 100%, 149%, 200%+)
- High relative volume premarket (5x+ vs same time historically)
- News catalyst: earnings beat, FDA approval, reverse split, sector news, short squeeze
- Premarket high visible as a clear breakout level
- Float preference: low-float amplifies the move; large-float gaps can work but require stronger catalyst

**Entry trigger:**
- Break of the premarket high on the 1-minute chart at or after 9:30 ET
- Alternatively: early premarket break of premarket high (seen from 6:55–8:00 AM entries in sample)
- Add-on mechanic: initial position at break, add on first pullback dips, pyramid adds as momentum confirms
- Example from sample (FILE 0004): sub-1M float, 185-to-1 reverse split, 5–6x rel vol, entry at $12.50 break, adds 2K→2K→2K→1.5K→4.5K→1.5K, stop on widening spreads/volume decline

**Hold duration norms:**
- Majority short (48%) or scalp (38%); extended holds (10%) occur on strong low-float runners with multiple halts
- Scalp: exit at first resistance or whole-dollar level above entry
- Short: ride to next level, VWAP, or daily high, trim on stalls
- Extended: only when stock halts up repeatedly and momentum doesn't break

**MACD relevance:** Low (3.7%) — gap-and-go is a momentum/price-action setup, not indicator-dependent. MACD confirmation is a bonus on borderline setups but not required.

**Use when:**
- Stock is the #1 or #2 leading gapper on the scanner
- Catalyst is clear and specific (not vague sector sympathy)
- Premarket volume is increasing into the open (not fading)
- Stock is trading above VWAP premarket

**Skip when:**
- Gap is on no news or unclear catalyst
- Premarket volume is thin and spread is wide
- Stock already up 50–100% with no halts — likely extended, not early
- Multiple sellers visible at the premarket high on Level 2

---

### 2. Dip-Buy

**n = 712 | Scalp 35.8% / Short 46.8% / Extended 6.2% | MACD relevance 4.4%**

**Definition:** Entry on a pullback from a momentum high, anticipating continuation to a new high. The dip is a temporary consolidation or shakeout on a stock still in upward trend.

**Setup criteria:**
- Stock has already moved (gap, news pop, halt squeeze) — dip-buy is a second/third entry, not the initiating trade
- Pullback holds above a key level: VWAP, whole-dollar, EMA-9, or prior breakout level
- Volume on the dip is declining (sellers flushing, not distributing)
- Best on low-to-mid float stocks where one buyer can rip it back
- Seen on premarket dips (FILE 0005: dip at $3.50 premarket, added at $4.00, target $4.40–$4.50) and intraday dips (FILE 0006: break of $3.50, aggressive 3K→6K→9K)

**Entry trigger:**
- Price stabilizes at support level (VWAP, whole-dollar, EMA-9) and starts to curl up
- Level 2 shows buyers stacking bid vs sellers clearing ask
- 1-minute candle closes green after a red candle sequence
- Add-on: pyramid dips in the direction of trend (FILE 0017: 2.5K→5K→7.5K→10K→12.5K→15K→17.5K)

**Hold duration norms:**
- Short hold (47%) is modal — ride to new high of day, exit on failure to make new high
- Scalp (36%) when the bounce is quick and stock stalls at resistance
- Extended (6%) on sympathy plays or multi-move runners

**MACD relevance:** Slightly higher than gap-and-go (4.4%) — positive MACD cross on the dip recovery adds conviction for add-on entries.

**Use when:**
- Stock is the leading mover and has already proven it can bounce
- Dip is to a clean technical level with identifiable stop below it
- First dip is typically the best — each subsequent dip carries more fade risk
- Hot market day (many gappers, sector runners)

**Skip when:**
- Dip breaks below VWAP and does not reclaim quickly — structure broken
- Stock is showing L2 distribution (big sellers, step-down asks)
- Dip occurs after 11 AM — morning momentum gone, chop risk high
- More than 2–3 failed dip attempts on same stock same day

---

### 3. Whole-Dollar Break

**n = 428 | Scalp 50.9% / Short 39.0% / Extended 6.3% | MACD relevance 2.3%**

**Definition:** Entry at the break of a round whole-dollar or half-dollar price level ($3.00, $5.00, $7.50, etc.) where psychological resistance concentrates sellers and triggers stops/chases above.

**Setup criteria:**
- Stock is approaching a whole- or half-dollar level with momentum
- Level is visible as recent resistance on the 1-minute or 5-minute chart
- Relative volume is elevated (5x+) — thin stocks can fake breaks
- Float: works best on low-to-mid float where fewer shares need to transact to push through
- Examples: FILE 0115 (break of whole dollar, target $1.05); FILE 0503 (whole-dollar break through resistance level); FILE 0500 (break of $2.00)

**Entry trigger:**
- Price closes a 1-minute candle above the whole/half-dollar level with conviction
- Alternatively: anticipatory entry just below the level with stop below prior candle low
- Common add-on: re-enter on first pullback to the broken level (former resistance becomes support)

**Hold duration norms:**
- Predominantly scalp (51%) — whole-dollar breaks are often fast moves to the next level and stall
- Short (39%) when momentum carries through multiple levels
- Extended rare (6%) — typically only when the dollar break is also a multi-day breakout

**MACD relevance:** Low (2.3%) — pure price-action / psychology setup. MACD not a primary factor.

**Use when:**
- The whole-dollar level is clearly the current resistance (tested 2+ times)
- Volume is expanding into the approach, not contracting
- Stock is in a confirmed uptrend (green day, above VWAP)
- The break is paired with another catalyst (news continuation, halt resume, premarket high)

**Skip when:**
- Stock is extended far above VWAP — whole-dollar break at extremes fades fast
- Level is a daily chart resistance, not just intraday — requires larger position management
- Spreads are wide at the level (low liquidity) — risk of getting filled poorly on both sides
- Second or third attempt at the same level same day — exhaustion likely

---

### 4. Micro-Pullback

**n = 387 | Scalp 43.7% / Short 36.7% / Extended 9.3% | MACD relevance 4.7%**

**Definition:** Entry on a 1–3 candle consolidation or pullback within a strong momentum move, typically the first pause after an initial surge. The pullback is shallow and the trend is still intact.

**Setup criteria:**
- Stock is in a confirmed uptrend on the 1-minute chart (higher highs, higher lows)
- Pullback is 1–3 candles, no deeper than 30–50% of the prior up-leg
- Pullback holds above the EMA-9 on the 1-minute chart
- High relative volume on the up-move (confirms buyers in control)
- Best on low-float stocks (FILE 0002: sub-1M float, micro-pullback on news catalyst; FILE 0027: rapid entries at $3.35, $3.70, $3.90 on dips)

**Entry trigger:**
- First 1-minute candle that closes above the high of the pullback candle(s)
- Alternatively: break of the consolidation high as price curls up
- Add-on mechanic: add on each successive micro-pullback as the trend continues (FILE 0027: multiple rapid entries on dips during strong run)

**Hold duration norms:**
- Near equal split: scalp (44%) vs short (37%), with meaningful extended (9%) on strong runs
- Extended holds associated with low-float stocks halting up during the micro-pullback sequence
- Scale out at each resistance level; don't hold the full position to extended

**MACD relevance:** Highest of all patterns at 4.7% — positive MACD cross adds conviction on the pullback re-entry. Check that MACD hasn't crossed negative on the pullback (would signal trend change, not continuation).

**Use when:**
- First pullback on a strong gap-and-go or news mover — this is the cleanest entry
- Stock has proven momentum (multiple green 1-min candles before the pause)
- Premarket or first 30 minutes of trading — highest reliability window
- Low-float environment where moves are fast and clean

**Skip when:**
- Pullback is too deep — more than 50% retracement often means failed momentum
- Volume expands on the red candles (sellers taking over, not just profit-taking)
- EMA-9 is lost on the 1-minute — pattern integrity broken
- After 10:30 AM — micro-pullbacks in late morning often reverse into the mean

---

### 5. Halt-Resume

**n = 319 | Scalp 35.7% / Short 46.4% / Extended 7.5% | MACD relevance 2.8%**

**Definition:** Entry during or immediately after a circuit-breaker halt-up (LULD halt), anticipating continuation once trading resumes. The halt creates a forced pause that concentrates buyers and can result in a squeeze on resume.

**Setup criteria:**
- Stock has halted up (circuit breaker triggered — move of 10%+ in 5 minutes)
- Volume was high going into the halt — confirms genuine momentum, not thin-air move
- Premarket high or psychological level visible above current price as target
- Float: works on both low and mid-float; low-float halts tend to squeeze harder
- Examples: FILE 0008 (halt resume dip entry, target $5.88–$5.94); FILE 0016 (circuit breaker halt resume, dip entry after halt, target $2.10); FILE 0026 (halt resume rip, early session, target $10)

**Entry trigger:**
- Method 1 (aggressive): buy the ask immediately as trading resumes — captures the squeeze
- Method 2 (safer): wait for first pullback after resume — enter on first dip off the resumption spike
- Stop: below the resumption price (failure to hold halt level)
- Common in sample: "halt resume dip entry" — dip into the bid after the initial resumption squeeze

**Hold duration norms:**
- Short (46%) is modal — resume squeezes are fast, often peak in 5–15 minutes
- Scalp (36%) when the halt was late in the morning or the stock was already extended
- Extended (8%) on very strong low-float runners with multiple halts in sequence

**MACD relevance:** Low (2.8%) — halt-resume is event-driven. MACD state at halt is often unknown/irrelevant. Post-resume MACD can guide add-on decisions.

**Use when:**
- Halt occurs in first 90 minutes of trading (before 11 AM)
- Stock halted up on genuine momentum (not a spike from thin trading)
- Clear target level visible above resumption price (round number, premarket high)
- Multiple halts in sequence (second and third halts tend to extend the move)

**Skip when:**
- Halt is a halt-down (L-halt for news, regulatory) — different risk profile entirely
- Stock was already up 100%+ before the halt — exhaustion risk
- Resume fails to hold above halt price — failed resume, reverse quickly
- Spreads are very wide post-resume (market makers absent) — execution risk

---

### 6. VWAP Reclaim

**n = 153 | Scalp 25.5% / Short 43.8% / Extended 11.8% | MACD relevance 2.6%**

**Definition:** Entry when a stock that has traded below VWAP reclaims and holds above it, signaling a shift from seller control to buyer control. The VWAP reclaim is a trend change signal, not a continuation signal.

**Setup criteria:**
- Stock was above VWAP earlier (gap-and-go, news pop) and pulled back below it
- Price tests VWAP from below and closes a 1-minute candle above it with volume
- Relative volume remains elevated (confirms buyers present, not just thin bounce)
- Best when VWAP reclaim coincides with other support: whole-dollar, EMA-9, or prior breakout level
- Examples: FILE 0019 (VWAP break, halt squeeze, extended hold); FILE 0308 (VWAP reclaim, news pop curl-back, 7am entry, short hold, target $4.84); FILE 0348 (180% gap, VWAP reclaim with add on move, target $6.18)

**Entry trigger:**
- 1-minute candle closes above VWAP with above-average volume
- Add on first successful test of VWAP from above (former resistance becomes support)
- Stop: close back below VWAP on volume — position invalidated

**Hold duration norms:**
- Extended (12%) is highest of all patterns after gap-and-go — VWAP reclaims set up for longer moves
- Short (44%) is modal — aim for prior high or next resistance level
- Scalp (26%) when the reclaim fails to generate immediate follow-through

**MACD relevance:** Low (2.6%) — MACD positive cross concurrent with VWAP reclaim adds confidence but the VWAP level itself is the primary signal.

**Use when:**
- Morning session (before 11 AM) — VWAP reclaims in afternoon are less reliable
- Stock has a news catalyst still in play (not just a technical bounce)
- The pullback below VWAP was on declining volume (sellers exhausted)
- First VWAP test of the day — subsequent tests have lower success rate

**Skip when:**
- Stock is below VWAP for more than 30 minutes — trend broken, not just a pullback
- Multiple failed VWAP reclaim attempts same day
- VWAP is declining (downtrend) — reclaiming a falling VWAP is different from a flat/rising VWAP
- After 11 AM — afternoon VWAP reclaims lack morning momentum to sustain

---

### 7. Red-to-Green

**n = 143 | Scalp 51.7% / Short 40.6% / Extended 3.5% | MACD relevance 2.1%**

**Definition:** Entry when a stock that opened red (below prior day close) makes a move to green (above prior day close). The red-to-green level acts as a psychological trigger for short covering and momentum buying.

**Setup criteria:**
- Stock gapped down or opened red relative to prior close
- Catalyst still active (news continuation, sector move, short squeeze developing)
- Price approaches the prior close level (the "green line") with increasing volume
- Best on stocks that had a strong prior day (former runner, high of day yesterday)
- Examples: FILE 0012 (red-to-green false breakout, 9K shares, rejected at $3.80, target $4.10); FILE 0018 (red-to-green move, high of day, scalp, target $15); FILE 0822 (squeeze up, sell into momentum spike, target $18.19); FILE 0834 (first new high, scaled exits, target $3.85)

**Entry trigger:**
- Price breaks above the prior day close level with a full 1-minute candle close above it
- Volume must expand on the break (thin breaks above prior close fail frequently)
- Stop: back below prior close (failed red-to-green)
- Note from sample: false breakouts on red-to-green are common — tight stops essential

**Hold duration norms:**
- Predominantly scalp (52%) — red-to-green moves are often short-lived squeezes
- Short (41%) when the catalyst is strong and VWAP is reclaimed concurrently
- Extended almost never (3.5%) — fade risk is high once short-covering exhausts

**MACD relevance:** Lowest of major patterns (2.1%) — pure price-level psychology setup.

**Use when:**
- Stock has a fresh catalyst today (not just yesterday's leftover momentum)
- The red-to-green level is within 5–10% of current price (not a massive gap to close)
- Volume is building as price approaches the level (anticipatory demand)
- Hot market day — risk-on environment increases success rate

**Skip when:**
- Stock is down significantly (30%+) — red-to-green is very far away and unlikely
- No current catalyst — without fresh news, red-to-green is just a mean-reversion attempt
- Already tested red-to-green twice and failed — third attempt rarely succeeds
- Late morning or afternoon — red-to-green setups are early-session plays only

---

### 8. Flat-Top

**n = 82 | Scalp 54.9% / Short 37.8% / Extended 7.3% | MACD relevance 1.2%**

**Definition:** A stock consolidates at a price ceiling for multiple candles, creating a horizontal "flat top" resistance. Entry on the break above this level as the consolidated supply is absorbed.

**Setup criteria:**
- Price tests the same resistance level 2–4 times on the 1-minute chart without breaking through
- Each test on declining selling volume (supply being absorbed)
- The flat top is often visible premarket (FILE 0026: flat top break premarket, 250–500 share positions, target $57.20)
- Also occurs intraday as an opening range consolidation before a move
- Examples: FILE 0008 (consolidation entry $4.46–$4.47, squeeze to $5.08, short hold); FILE 0111 (flat bottom double bottom break, extended hold, target $30+); FILE 0719 (flat-top breakout, multiple dips, scaled exits, target $3.05 premarket)

**Entry trigger:**
- 1-minute candle closes above the flat-top resistance level with volume expansion
- Anticipatory entry: buy just below the level with limit order, with stop below the consolidation base
- Add-on: add on first pullback to the former flat-top level (now support)

**Hold duration norms:**
- Predominantly scalp (55%) — flat-top breaks often result in quick moves to next resistance then stall
- Short (38%) when the stock has premarket momentum and the break is at open
- Extended (7%) rare — usually on premarket flat-tops that continue into market open

**MACD relevance:** Lowest of all patterns (1.2%) — flat-top is a consolidation breakout, not indicator-driven. By the time MACD would confirm, the move is already underway.

**Use when:**
- Flat top visible on the 1-minute chart with at least 3 candle tests
- Volume on each test is declining (sellers running out)
- The level is also a technical reference: premarket high, prior day high, or half/whole-dollar
- Premarket flat tops are especially reliable — less noise, cleaner levels

**Skip when:**
- Only 1–2 candle tests — not enough consolidation to confirm supply exhaustion
- Volume on tests is constant or increasing (active sellers, not absorbed supply)
- Stock is extended far above VWAP — flat-top break at extended price has high fade risk
- After 11 AM — flat-top breaks in late morning often reverse quickly

---

### 9. ABCD

**n = 26 | Scalp 15.4% / Short 73.1% / Extended 11.5% | MACD relevance 0.0%**

**Definition:** A four-leg technical pattern: A (initial impulse high) → B (pullback) → C (secondary push toward A) → D (breakout above A to new high). Entry is at the D-leg breakout above the prior A high.

**Setup criteria:**
- Clear A leg: initial momentum push to a high
- B leg pullback: 30–60% retracement of A leg, holds above VWAP
- C leg: recovery push that approaches but ideally does not exceed A (sets up the breakout tension)
- D leg trigger: break above A high on expanding volume
- Requires structural integrity — ABCD below VWAP noted in sample as "risky" (FILE 1423)
- Best on low-float stocks where the pattern completes in 5–15 minutes
- Examples: FILE 0110 (130% gap, ABCD second entry, target $3.23, short hold); FILE 1400 (very-high rel vol, ABCD momentum squeeze, multiple re-entries, target $9.50+); FILE 1288 (119% gap, ABCD resistance break — noted as "bad setup")

**Entry trigger:**
- Price breaks above the A-leg high with volume; enter on the break or on the first 1-minute close above A
- Stop: below the C-leg low (failed ABCD — pattern collapses)
- Add-on mechanic: multiple re-entries seen in sample on strong ABCD days

**Hold duration norms:**
- Strongly skewed to short (73%) — ABCD is a multi-minute pattern, not a scalp; hold for next measured move
- Extended (12%) possible on very strong momentum stocks
- Scalp (15%) only when D-leg fizzles quickly

**MACD relevance:** 0.0% — no MACD-positive trades recorded in this sample for ABCD. The pattern itself provides the directional signal.

**Use when:**
- Pattern is above VWAP throughout
- A and B legs are clean and identifiable on the 1-minute chart
- High relative volume on the A and C legs
- Strong catalyst still in play (not a stale mover)

**Skip when:**
- Pattern is below VWAP (noted explicitly as risky in sample)
- C leg exceeds A leg — pattern becomes extended double-top risk
- B leg is shallow (less than 20% retracement) — not enough tension built
- After 11 AM — ABCD patterns require momentum that fades in late morning

---

### 10. Bull-Flag

**n = 26 | Scalp 34.6% / Short 38.5% / Extended 11.5% | MACD relevance 0.0%**

**Definition:** A consolidation pattern following a sharp impulse move (the "pole"), where price drifts sideways or slightly lower in a tight range before breaking higher. The flag represents controlled selling after a strong move.

**Setup criteria:**
- Strong impulse "pole" move: 20%+ in 1–5 minutes
- Consolidation phase: 3–10 candles of sideways/slight drift, volume declining
- Flag holds above EMA-9 or key support level
- Best on 5-minute chart patterns (FILE 0015: 5-minute flag breakout, first daily candle, target $1.50)
- Also seen as multi-day patterns (FILE 0880: multi-day bull flag continuation pattern)
- Examples: FILE 1403 (5-minute flag break, scaled on pullback, pullback rejection, target $3.00+); FILE 1414 (bull flag breakout, second entry, multiple dip scalps, target $0.90); FILE 1415 (break of premarket bull flag $3.18, short hold)

**Entry trigger:**
- Break above the upper boundary of the flag (the consolidation high) on a 1-minute or 5-minute candle close
- Volume must re-expand on the break (confirms buyers returning)
- Stop: below the low of the flag consolidation

**Hold duration norms:**
- Near equal scalp/short/extended split (35%/39%/12%) — more variable than most patterns
- Target: measured move = flag breakout point + pole length
- Extended (12%) on flags forming on multi-day charts or strong sector days

**MACD relevance:** 0.0% — no MACD-positive trades in sample. Bull-flag is a price-action continuation pattern.

**Use when:**
- Flag forms immediately after the impulse (first 5–10 minutes of the move)
- Volume on the flag is clearly declining (healthy consolidation)
- First flag of the day — subsequent flags are less reliable
- Hot market day with sector momentum behind the stock

**Skip when:**
- Flag volume is flat or increasing — not healthy consolidation, possible distribution
- Flag lasts more than 15–20 minutes without breaking — enthusiasm fading
- After 11 AM — flags need morning momentum to power the breakout
- Flag drops below EMA-9 — structure broken, likely failed breakout

---

## Pattern Selection Logic

### (a) Premarket vs Market Hours

| Context | Preferred Pattern(s) | Reasoning |
|---------|---------------------|-----------|
| **4 AM – 8 AM** | Flat-top (premarket level building), Gap-and-go (premarket high setting up), VWAP reclaim (if prior day runner) | Low volume; clean level-based setups work better than momentum patterns. Flat tops are cleaner in premarket. |
| **8 AM – 9:30 AM** | Gap-and-go (premarket squeeze), Dip-buy (premarket dip recovery), Bull-flag (premarket flag forming) | Volume picking up; momentum setups become viable. Premarket high break is primary entry type. |
| **9:30 – 10:00 AM** | Gap-and-go (first 5 min), Micro-pullback (first pullback), Red-to-green (morning squeeze) | Opening range — highest energy window. All momentum patterns valid; prefer first-instance setups only. |
| **10:00 – 11:00 AM** | Dip-buy (first dip of move), VWAP reclaim (if pulled back), Halt-resume (if halts occurring), Whole-dollar-break | Secondary entries on morning runners. VWAP and whole-dollar levels are now established. |
| **11:00 AM+** | Avoid all except Halt-resume (if active) | Morning momentum gone. Pattern reliability drops sharply after 11 AM. Red-to-green, micro-pullback, flat-top all degraded. |

---

### (b) Hot vs Cold Market

| Market Condition | Preferred Patterns | Patterns to Downgrade |
|-----------------|-------------------|----------------------|
| **Hot market** (multiple 50%+ gappers, VIX stable, sector runners) | Gap-and-go, Micro-pullback, ABCD, Halt-resume | None — all patterns have tailwind |
| **Moderate market** (1–2 strong gappers, mixed sector) | Dip-buy, Whole-dollar-break, VWAP reclaim | ABCD (needs strong momentum), Extended holds on micro-pullback |
| **Cold market** (no gappers, VIX elevated, choppy open) | Flat-top (cleaner setups when slow), Red-to-green (if individual catalyst) | Gap-and-go (no candidates), Micro-pullback (no trends), ABCD, Bull-flag |
| **Market selloff day** | Skip most setups; halt-resume only on short-squeeze stocks | Everything trend-following |

**Hot market indicators:** 5+ stocks up 20%+ premarket, relative volume across scanner elevated, first 5-minute candles strong green across multiple names.

**Cold market indicators:** Scanner showing only 1–2 names with thin volume, gap-and-go fails at open, first red day in sector.

---

### (c) Low-Float vs Mid-Float Stock

| Float Category | Best Patterns | Cautions |
|---------------|---------------|----------|
| **Sub-1M float** | Micro-pullback (fastest moves), Halt-resume (extreme squeezes), Gap-and-go (amplified) | Spreads can be 5–20 cents; position size down. ABCD patterns very compressed. Exits must be fast. |
| **1M – 5M float (low-float)** | All patterns viable; micro-pullback and halt-resume strongest | Dip-buy entries can be wider; watch for thin L2 above entry. VWAP reclaim and flat-top reliable. |
| **5M – 20M float (mid-float)** | Gap-and-go, Dip-buy, Whole-dollar-break, VWAP reclaim, Bull-flag | Micro-pullback less explosive (more shares to absorb). Extended holds harder. Patterns take longer to develop. |
| **20M+ float (high-float)** | Gap-and-go (only with very strong catalyst), VWAP reclaim, Red-to-green | Micro-pullback rarely works — too much supply. Halt-resume less explosive. Avoid ABCD/flat-top on high-float — insufficient leverage. |

**Float interaction with hold duration:** Low-float stocks skew toward extended holds (more likely to halt up multiple times). High-float stocks skew toward scalp/short (moves exhaust faster against larger supply).

**Float interaction with position sizing:** Sub-1M float requires smaller share counts (wide spreads, thin book). As float grows, position can scale up but per-share movement shrinks. Relative expected value should be similar across floats when properly sized.

---

*End of Pattern Playbook*
