# jTrader Algorithm Rule Extraction — Project Briefing

## Project Overview
Extract TRADE-level rules from ~1,799 Ross Cameron day trading video transcripts to inform jTrader day trading algorithm development. Focus: individual trade entry/exit decisions, NOT account-level behavioral rules.

**Goal**: Build actionable rule database for algorithmic trading system by analyzing real-world trading session recordings.

---

## Current Progress
- **Status**: 540 of 1,799 transcripts analyzed (30.0% complete)
- **Master Document**: `TRANSCRIPT_SUMMARIES_MASTER.md`
- **Next Batch**: FILES 0541-0550 (sequential, single-file approach)

---

## ⚠️ FORMAT STANDARD — ENFORCE THIS EXACTLY (Zone 5)

Every transcript entry must have **three sections** in this exact order:

---

### SECTION 1 — Structured Header (pipe-delimited line + OUTCOME on separate line)

```
FILE XXXX | TYPE: [classification] | SCRN: [pre-screen rules] | ENTRY: [entry patterns] | STOP: [stop rules] | PROF: [profit rules] | ACCT-LEVEL: [account metrics]

OUTCOME: [session result]
```

**Field definitions:**

- **TYPE**: One of: `Daily Recap` / `Live Morning Show` / `Educational` / `Multi-Stock Comparison` / `Market/Psychological Focus` / `Wild Card / Multi-Day`
- **SCRN**: Float thresholds, price range, volume multiplier, gap %, news catalyst requirements, any pre-market filter criteria
- **ENTRY**: Specific entry patterns with trigger conditions and price mechanics (e.g., VWAP break at $X, first 1-min candle new high, halt-resume dip, micro-pullback off $Y support)
- **STOP**: Specific exit-loss conditions (MACD divergence, spread >X cents, failed breakout, volume decline, halt flush)
- **PROF**: Profit capture mechanics (whole-dollar targets, partial scaling at X%, halt squeeze targets, time-based exits)
- **ACCT-LEVEL**: Daily P&L, running totals, position sizing notes, emotional state flags (flag with [ACCT] prefix — Phase 2 use only)
- **OUTCOME**: `+$X,XXX green` or `-$X,XXX red` or `mixed`, plus win/loss trade count if available (e.g., `+$4,200 green / 6 trades / 4W-2L`)

---

### SECTION 2 — Trade Log (one line per discrete trade, best-effort)

Extract each identifiable trade from the transcript in this format:

```
[SIGNAL: entry trigger] → [EXIT: exit reason] → [RESULT: +/-$X] → [WIN/LOSS]
```

**SIGNAL options** (use exact labels for consistency):
- `VWAP break` / `VWAP reclaim` / `VWAP curl`
- `momentum scanner hit`
- `gap-and-go open`
- `halt-resume dip`
- `micro-pullback 1-min`
- `first 1-min candle new high`
- `whole-dollar break ($X.00)`
- `consolidation breakout`
- `reverse split squeeze`
- `red-to-green bounce`
- `news catalyst spike`
- `ABCD pattern`
- `flat-top breakout`
- `opening range breakout`
- `[other: describe briefly]`

**EXIT options** (use exact labels):
- `profit target ($X.XX)`
- `MACD divergence`
- `spread widening`
- `failed breakout`
- `halt flush`
- `volume decline`
- `time-based (10:30 AM)`
- `partial scale-out`
- `max loss hit`
- `[other: describe briefly]`

**RESULT**: Dollar amount won or lost on that specific trade. If unavailable, write `RESULT: unknown`.

**Notes on Trade Log:**
- Include all identifiable individual trades, even if only partially documented
- If a transcript has 10+ trades on one stock, capture the distinct entry setups, not every execution
- It is OK if some trades only have 2 of 3 fields — partial data is still useful
- Do NOT fabricate numbers. If the trader doesn't state P&L for a specific trade, write `RESULT: unknown`

**Example Trade Log:**
```
[SIGNAL: VWAP break] → [EXIT: profit target ($6.10)] → [RESULT: +$1,400] → [WIN]
[SIGNAL: micro-pullback 1-min] → [EXIT: failed breakout] → [RESULT: -$600] → [LOSS]
[SIGNAL: halt-resume dip] → [EXIT: spread widening] → [RESULT: +$800] → [WIN]
[SIGNAL: whole-dollar break ($5.00)] → [EXIT: MACD divergence] → [RESULT: unknown] → [WIN]
```

---

### SECTION 3 — Session Summary (narrative paragraph)

150-200 words capturing: session context, key winners with profit numbers, failure patterns, overall P&L, and any emerging patterns. Write in plain prose, no bullet points.

---

## Complete Entry Example

```
FILE 0451 | TYPE: Daily Recap | SCRN: low float <5M/news catalyst/crypto uplift/reverse split pop | ENTRY: VWAP break (AXIL $12.00)/knee-jerk reversal (CRBP $13.00 after drop)/micro-pullback dip (BTTC $4.80 starter)/whole-dollar break ($5.00+ adds) | STOP: hard rejection (AXIL stop at $11.00)/spread widening on BTTC starter hold | PROF: CRBP $13→$14.50 scale-out/MIGI pops to $9.50-$11 scale/BTTC pull-away $5→$12 scale | ACCT-LEVEL: [ACCT] +$42,846 day/$187K December MTD/5-pillar add discipline

OUTCOME: +$42,846 green / 4 stocks / 2W-2L net

[SIGNAL: VWAP break] → [EXIT: profit target ($12.50)] → [RESULT: +$5,000] → [WIN]
[SIGNAL: whole-dollar break ($12.00)] → [EXIT: failed breakout] → [RESULT: -$14,000] → [LOSS]
[SIGNAL: news catalyst spike] → [EXIT: profit target ($14.50)] → [RESULT: +$7,137] → [WIN]
[SIGNAL: micro-pullback 1-min] → [EXIT: partial scale-out] → [RESULT: +$3,369] → [WIN]
[SIGNAL: flat-top breakout] → [EXIT: halt flush] → [RESULT: unknown] → [LOSS]
[SIGNAL: momentum scanner hit] → [EXIT: profit target ($12.00)] → [RESULT: +$41,000] → [WIN]

Exceptional +$42,846 session starting -$9k from an AXIL misread. AXIL (Walmart distribution news, +160% pre-market): first VWAP break at $12 yielded +$5k; second add on inverted H&S pattern at $11.50-$12 (25k shares) caught hard rejection to $11 stop = -$14k. Revised position after recognizing low-margin retail catalyst was weak. CRBP (7am news, knee-jerk drop $12→$8 then reversal): bought $13 break, scaled to $14.50, +$7,137. MIGI (reverse split pop, third attempt in three days): curl back to $9.50, pops to $10-$11 range, +$3,369 on dip-curl adds. BTTC (crypto stock uplift to NASDAQ, highest-volume NYSE day ever): $4.80 starter, held through -50¢ dip, re-entered $5+ through pull-away pattern to $12, +$41k main driver. Week swing -$38k Monday to +$50k Tuesday-Thursday = $187k December month-to-date.
```

---

## Key Patterns Identified (cumulative)

### Entry Mechanics (TRADE-LEVEL)
1. **VWAP Reclaim Entries** — Stock dips below VWAP on news spike, breaks back above = high-probability continuation
2. **Whole-Dollar Scaling** — Target every $1.00 increment for position adds
3. **Micro-Pullback Dip-Buys** — 10-15 cent dips off moving averages = re-entry points
4. **First 1-Minute Candle to New High** — After VWAP reclaim or consolidation break = confirmation signal
5. **Halt-Resume Dip-Rip** — Stock halts, resumes lower, bounces sharply back = scalp target
6. **Consolidation Breakouts** — Ascending support lines + whole-dollar breaks = aggressive scaling
7. **Reverse Split Squeeze** — Float reduction triggers multi-halt explosive moves
8. **Red-to-Green Bounce** — Short covering after gap-down open reclaims prior close

### Stop Rules (TRADE-LEVEL)
- MACD divergence (price up, MACD down) = immediate exit
- Volume decline on breakout = reduce/exit
- Spread widening > 15 cents = hard stop
- Failed first 1-min to new high = reduce immediately
- Multiple false breakouts at same level = stop trading stock
- Halt flush on resume (opens lower, continues lower) = exit immediately

### Profit Rules (TRADE-LEVEL)
- Take 25-50% at first whole-dollar break
- Scale out at each whole-dollar resistance
- Halt squeeze targets = near halt price on resume bounce
- Parabolic divergence (MACD negative despite new highs) = exit signal
- Time-based: 10:30 AM threshold = close remaining positions

### Pre-Screen Rules (SCRN)
- **Float < 10M** = higher volatility, tighter squeezes preferred
- **Price $1-$10** = sweet spot (execution, spreads manageable)
- **Relative volume > 3x average** = volume confirmation required
- **Gap > 5% premarket** = morning session candidate
- **News catalyst present** = highest conviction setups
- **Reverse splits** = float reduction = potential multi-halt catalyst

---

## Processing Specifications

### Agent Configuration — SEQUENTIAL SINGLE-FILE APPROACH (Optimized)
- **Processing Method**: One transcript at a time, sequentially
- **Why**: Keeps session context lean, eliminates batch inconsistency risk, maximizes analytical capability per file
- **Workflow**: Load transcript → Analyze → Write summary → Append to master → Clear context → Next file
- **Format**: Enforce Zone 5 exactly (Header → Trade Log → Session Summary)

**Note**: Previous parallel-batch approach (5 agents × 10 files) showed subtle inconsistency patterns. Sequential single-file processing is more reliable for algorithmic aggregation and prevents context bloat that reduces analytical depth.

### File Locations
- **Transcripts**: `/sessions/happy-focused-hawking/mnt/Ross Cameron Day Trading Videos/Text transcriptions/`
- **Master Document**: `/sessions/happy-focused-hawking/mnt/Ross Cameron Day Trading Videos/TRANSCRIPT_SUMMARIES_MASTER.md`

### Append Protocol
- Always read the master document tail before editing (to get correct anchor text)
- Append new entries at the END of the master document
- Verify line count after append

---

## Format Consistency Notes

The master document has format inconsistencies from earlier sessions (Files 1-450). Do NOT attempt to reformat those. Going forward (File 521+), strictly enforce the Zone 5 format above. If running a fill-in batch (e.g., missing files), also use Zone 5.

---

## Account-Level Rules (PHASE 2 — Future Use Only)

Flag with [ACCT] in ACCT-LEVEL field. Do not use for jTrader algorithm directly.

1. **Daily Goal Calibration**: $5K base-hit accumulation target
2. **Position Sizing After Losses**: 50-70% reduction on recovery trades
3. **Green-Day Preservation**: Protect small wins > chase large wins
4. **No-Trade Protocol**: Weak market = skip rather than force commissions
5. **Peak Trading Window**: 7-10:30 AM = profit zone; 2 PM+ = exponential loss risk

---

## Next Phase (After All 1,799 Transcripts)

1. **Signal Scoring Synthesis**: Aggregate TRADE_LOG entries across all files → calculate win rate and avg P&L per SIGNAL type
2. **Pattern Conflict Resolution**: Identify contradictions (e.g., when to trust VWAP vs. ignore)
3. **Numeric Threshold Optimization**: Determine precise float/gap/volume thresholds from data
4. **ACCOUNT-Level Phase 2**: Position-sizing and emotional regulation rules
5. **Algorithm Implementation**: Feed structured rules into jTrader

---

## Contact/Reference
- **User**: Joel Birdsall (joel.birdsall@gmail.com)
- **Project**: jTrader Algorithm Rule Extraction
- **Last Updated**: March 28, 2026 — Zone 5 format enforced, OUTCOME + TRADE_LOG fields added; sequential single-file processing adopted for context efficiency
