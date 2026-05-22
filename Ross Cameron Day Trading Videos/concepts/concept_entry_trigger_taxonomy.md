# Concept: Entry Trigger Taxonomy

**Last updated:** 2026-05-21  
**Source:** RC_STRATEGY_STATISTICS.md Section 3 (win rates, categories) + TRANSCRIPT_SUMMARIES_0001-1799 corpus (raw trigger label extraction, sub-variant analysis)  
**Sample size:** 5,261 trades across 1,787 sessions (RC_STRATEGY_STATISTICS); 5,091 raw ENTRY_TRIGGER values extracted from corpus TRADE_MECHANICS tables  
**Scope:** All named entry trigger categories, ranked by performance

---

## Definition

An entry trigger is the specific price action event that causes Ross to pull the trigger — distinct from the chart pattern that precedes it. A flat top is a pattern; "1-minute candle closes above flat resistance" is the trigger. This page catalogs every trigger category identified across the full trade sample, quantifies performance, and maps each to jTrader implementation status.

---

## Full Trigger Taxonomy — Ranked by Win Rate

| Category | Trades | Win Rate | Avg Result | Total P&L |
|---|---|---|---|---|
| gap-and-go | 404 | 78.2% | +$3,791 | +$1,478,491 |
| vwap-break/curl | 137 | 78.1% | +$7,126 | +$954,885 |
| micro-pullback | 350 | 74.3% | +$3,560 | +$1,196,044 |
| vwap-reclaim | 50 | 72.0% | +$6,920 | +$311,421 |
| opening-range | 48 | 70.8% | +$1,654 | +$76,092 |
| vwap-other | 98 | 70.4% | +$2,885 | +$271,236 |
| bull-flag/flat-top | 56 | 69.6% | +$2,134 | +$108,811 |
| halt-resume | 428 | 68.0% | +$654 | +$264,906 |
| red-to-green | 71 | 66.2% | +$216 | +$15,118 |
| continuation | 181 | 64.6% | +$2,308 | +$399,328 |
| pullback/dip | 944 | 64.0% | +$1,728 | +$1,534,292 |
| whole-dollar-break | 112 | 64.3% | +$1,477 | +$160,965 |
| other | 1,813 | 60.5% | +$1,268 | +$2,177,614 |
| breakout | 507 | 56.4% | +$1,093 | +$524,752 |
| reverse-split | 48 | 54.2% | +$1,138 | +$52,359 |
| abcd-pattern | 14 | 42.9% | +$2,740 | +$38,361 |

---

## Trigger Granularity — Raw Corpus Labels

Corpus ENTRY_TRIGGER field uses freeform labels. Below is how they map to the taxonomy categories above, with raw label counts. This table shows what's INSIDE each category and validates the mapping.

| Taxonomy Category | Raw Corpus Labels (count) | Total Corpus Mentions |
|---|---|---|
| **gap-and-go** | "break premarket high" (28), "break of premarket high" (27), "premarket high break" (10), "gap-and-go" (13), "gap-and-go/break of PM high" (10), "premarket-high" (6), "first candle new high" (5), "first 1-min candle new high" (5) | ~104 |
| **vwap-break/curl** | "VWAP break" (14), "break of VWAP" (8) | ~22 |
| **micro-pullback** | "micro pullback" (15), "micro pullback entry" (6), "1-min micro pullback" (5), "micro-pullback" (5) | ~31 |
| **vwap-reclaim** | "VWAP reclaim" (5), "V-WAP reclaim" (4) | ~9 |
| **opening-range** | "opening range breakout" (11) | 11 |
| **halt-resume** | "halt resume" (24), "halt resumption" (10), "resume" (9), "halt resume dip" (7), "halt resume squeeze" (6), "halt resume continuation" (5), "halt resume bounce" (4), "halt resume/continuation" (4) | ~69 |
| **pullback/dip** | "dip" (22), "dip re-entry" (17), "dip buy" (11), "pullback dip" (8), "dip entry" (7), "dip trades" (5), "dip trade" (5), "pullback entry" (4), "pullback" (4) | ~83 |
| **continuation** | "continuation" (14), "continuation breakout" (5), "squeeze continuation" (5) | ~24 |
| **whole-dollar-break** | "whole-dollar break" (11), "break of whole dollar" (8), "half-dollar break" (7) | ~26 |
| **bull-flag/flat-top** | "flag breakout" (7), "consolidation break" (5), "consolidation breakout" (5), "consolidation" (5) | ~22 |
| **breakout (generic)** | "breakout" (54), "breakout attempt" (18), "break of resistance" (10), "breakout entry" (5), "breakout momentum" (6), "daily breakout" (8) | ~101 |
| **squeeze** *(not in RC_STATS taxonomy — in "other" bucket)* | "squeeze" (16), "momentum squeeze" (15), "premarket squeeze" (5), "squeeze continuation" (5) | ~41 |
| **news-driven** *(in "other" bucket)* | "news pop" (13), "news catalyst" (8) | ~21 |
| **momentum/scalp** *(in "other" bucket)* | "momentum" (17), "momentum entry" (14), "momentum pop" (13), "momentum scanner" (10), "momentum spike" (8), "scalp" (20), "pop" (15), "scanner pop" (7), "scanner hit" (6), "scan-alert" (5) | ~115 |
| **sympathy plays** *(in "other" bucket)* | "sympathy momentum" (6) | 6 |

**Key finding:** The "other" bucket (1,813 trades, 60.5% win rate) contains at minimum: ~41 squeeze entries, ~21 news-driven entries, ~115 momentum/scalp entries. These are not random — they have structure. The "momentum" cluster especially (momentum + momentum entry + momentum pop + scanner pop = ~55 entries) likely has different win rates than unclassified noise.

---

## Tier Structure

### Tier 1 — High Confidence (≥70% win rate)

- **gap-and-go** — 78.2%, +$3,791 avg. Break of premarket high on open momentum with catalyst. Highest trade count in Tier 1.
- **vwap-break/curl** — 78.1%, +$7,126 avg. Highest dollar average of any category. Price breaking above VWAP with momentum, or curling up from below VWAP. Anticipatory vs. confirmatory — entry before price fully clears.
- **micro-pullback** — 74.3%, +$3,560 avg. Shallow pullback to EMA or prior breakout level during an uptrend. Enters on the next push, not the dip bottom.
- **vwap-reclaim** — 72.0%, +$6,920 avg. Price drops below VWAP, then recovers back above it. Entry on the reclaim candle confirming hold above. Second-highest dollar average.
- **opening-range** — 70.8%, +$1,654 avg. Break of the first 5- or 15-minute candle range. Clean, definable level. 48 trades — underrepresented, but performance is Tier 1.
- **vwap-other** — 70.4%, +$2,885 avg. VWAP-anchored entries that don't fit break/curl or reclaim specifically — bounces, tests, consolidations at VWAP. Partially subsumed by vwap-reclaim logic.

### Tier 2 — Reliable (65–70% win rate)

- **bull-flag/flat-top** — 69.6%, +$2,134 avg. Consolidation pattern followed by break of the upper boundary. Trigger: 1-minute candle close above resistance.
- **halt-resume** — 68.0%, +$654 avg. Entry at the candle following a circuit-breaker halt resume. High frequency (428 trades), lower avg P&L — tight scalp setup. Requires halt feed.

### Tier 3 — Acceptable (60–65% win rate)

- **red-to-green** — 66.2%, +$216 avg. Break above prior-day close (green). High false-breakout rate. Low dollar average — setup is prone to fakeouts.
- **continuation** — 64.6%, +$2,308 avg. Add-on entry during an extended move, not after a pullback. Entry DURING the run, not the dip.
- **whole-dollar-break** — 64.3%, +$1,477 avg. Break of a round psychological level ($3.00, $5.00, $7.50, etc.). Clean, coiled resistance — shorts stack at these levels, break triggers short covers and chasing.
- **pullback/dip** — 64.0%, +$1,728 avg. Entry into a pullback from a high. Highest volume category (944 trades, 18% of all trades).

### Below Threshold (<60% win rate)

- **other** — 60.5%, 1,813 trades. Largest single bucket. Opportunistic, L2-read, news-driven, or gut-feel entries that don't map to a named pattern. Ross's overall win rate is 64.8% — this category is a drag on it.
- **breakout** — 56.4%, 507 trades. Generic resistance break without a specific anchor (not premarket high, not whole-dollar, not VWAP, not opening range). Underperformance confirms: breakouts without a precise trigger level are noise.
- **reverse-split** — 54.2%, 48 trades. Post-reverse-split momentum. Below threshold, limited sample.
- **abcd-pattern** — 42.9%, 14 trades. A=high, B=pullback, C=second high, D=second pullback, entry at break of C. Net-losing by win rate. Disabled in jTrader (Trial 193). Correct decision.

---

## Key Findings

### VWAP cluster dominates

vwap-break/curl (78.1%, +$7,126), vwap-reclaim (72.0%, +$6,920), and vwap-other (70.4%) occupy three of the top six slots. No other indicator family — EMA, MACD, opening range — clusters this strongly. The trigger that matters most is price's relationship to VWAP.

### Generic breakout is a trap

507 trades at 56.4%. The breakout category represents entries at arbitrary resistance without a specific, named anchor. Comparing it to other breakout-style triggers with defined levels (premarket high = 78.2%, opening range = 70.8%, whole-dollar = 64.3%) confirms the pattern: the anchor level is doing the work. Without one, win rate drops below 60%.

### Squeeze trigger missing from taxonomy

Corpus shows ~41 squeeze-labeled entries ("squeeze", "momentum squeeze", "premarket squeeze", "squeeze continuation"). These are classified as "other" or "continuation" in RC_STRATEGY_STATISTICS.md, so they don't have a separate win rate in the taxonomy table. Given squeeze's documented behavior (momentum acceleration at resistance, shorts covering, can run multi-leg), it likely has a win rate between halt-resume (68%) and gap-and-go (78%). Worth separating in a future data pass.

**jTrader implication:** The squeeze trigger needs a named implementation. See `concept_pattern_playbook.md` Pattern 11. Current jTrader catches squeeze mechanics via micro-pullback detection during momentum runs but doesn't explicitly classify the trigger.

### Halt-resume has 4 distinct sub-variants

The 428 halt-resume trades aggregate very different entry mechanics:

| Sub-Variant | Corpus Count | Mechanics | Risk Level |
|---|---|---|---|
| "halt resume" (generic) | 24 | Enter at any point on resume | Moderate — timing uncertain |
| "halt resume dip" | 7 | Enter the first dip after resume spike | Lower — defined entry after initial volatility clears |
| "halt resume squeeze" | 6 | Enter the continuation squeeze post-resume | Higher — requires momentum confirmation |
| "halt resume bounce" | 4 | Enter bounce off lower level at resume | Moderate — counter-move entry |
| "halt resume continuation" | 5 | Enter second/third halt resume | Lower risk — trend confirmed by multiple halts |

**jTrader implication:** If halt-resume is implemented, "halt resume dip" is the safest sub-variant (enter after the initial volatility spike, not at the spike itself). "halt resume continuation" (multiple halts) is also well-defined.

### ABCD is dead

14 trades, 42.9%. Disabled in jTrader after Trial 193. The data confirms the optimizer found the correct answer. ABCD's A-to-C structure introduces too much timing noise for low-float momentum stocks.

### "other" is the slippage bucket

1,813 trades at 60.5% — Ross's non-rule trades. He reads L2, feels market temperature, reacts to news. These trades collectively underperform his named patterns (64.8% overall). Automating the named patterns and skipping unclassified triggers is the right architecture choice.

**Corpus decomposition of "other":** Raw corpus labels reveal the composition includes: momentum/scalp entries (~115), squeeze entries (~41), news-driven entries (~21), sympathy plays (~6), and miscellaneous scan-based setups (~25). None of these have standalone win rate data yet. If squeeze entries average ~70% (reasonable estimate given the pattern), separating them from generic "other" would meaningfully improve "other"'s true average.

### "false breakout" entries — edge case

Corpus has 5 trades explicitly labeled "false breakout" as the ENTRY_TRIGGER. These are not trades that turned into false breakouts — they are entries *anticipating* the false breakout. I.e., Ross entered short-biased or on the expected fade of a breakout. This is a counter-trend play. Sample too small to quantify win rate, but worth flagging as a documented trigger type not in the taxonomy.

### Daily breakout — daily chart trigger

8 corpus entries labeled "daily breakout" or "break daily high" — these are entries at daily chart resistance levels (52-week high, multi-month high), not just intraday levels. Higher-stakes, larger potential targets. Currently lumped into "breakout" (56.4%) but are higher-quality setups due to the larger timeframe anchor. Would likely separate above the generic breakout win rate if isolated.

### Sympathy plays as explicit trigger

6 entries labeled "sympathy momentum" as the ENTRY_TRIGGER. These are entries on secondary stocks riding a leading gapper's momentum. Currently in "other" bucket. No win rate data available from corpus. See `concept_pattern_playbook.md` section (e) Sympathy Plays.

### Pattern vs. trigger distinction

A pattern defines chart structure. A trigger defines the specific price action event firing the order. They are paired:

| Pattern | Trigger |
|---|---|
| flat top | 1-minute candle closes above flat resistance |
| micro-pullback | first candle closing above EMA after pullback |
| VWAP reclaim | candle closes above VWAP after dip below |
| gap-and-go | candle closes above premarket high |
| opening range | candle closes above first 5- or 15-minute range high |
| whole-dollar break | candle closes above round/half-dollar level |

The trigger is the entry condition in code, not the pattern label.

---

## jTrader Coverage Table

| Entry Trigger | jTrader Status | Recommendation |
|---|---|---|
| gap-and-go | Implemented (commit 44c0423) | Keep. #1 setup by win rate and volume. |
| vwap-break/curl | Partial — vwap-reclaim implemented; break/curl is anticipatory | Implement break/curl as enhancement pass |
| micro-pullback | Implemented | Keep. |
| vwap-reclaim | Implemented (commit 0f7f61f) | Keep. |
| opening-range | Not implemented | Consider adding — 70.8% win rate, clean definable trigger |
| vwap-other | Not categorized explicitly | Partially covered by vwap-reclaim |
| bull-flag/flat-top | flat_top implemented; bull_flag disabled (Trial 193) | Re-evaluate bull_flag with current data |
| halt-resume | Not implemented | Nice-to-have. Requires halt feed integration. |
| red-to-green | Not implemented | Low priority — 66.2% but high false-breakout rate, low avg P&L |
| continuation | Not implemented as explicit pattern | Handled by add-on / scaling logic |
| pullback/dip | dip_buy implemented | Keep. Highest trade volume category. |
| whole-dollar-break | Not implemented | Consider — 64.3% win rate, clean and automatable trigger |
| breakout (generic) | flat_top catches some; no generic breakout logic | De-prioritize — 56.4% is below threshold |
| reverse-split | Not implemented | Skip — 54.2% win rate, limited edge |
| abcd | Disabled (Trial 193) | Keep disabled. 42.9% is net-losing. |

---

## jTrader Decision Rules

Priority order when multiple triggers are present on the same symbol at the same time — score and rank by expected value (win rate × avg result):

```
TRIGGER_PRIORITY = [
    "gap-and-go",         # 78.2% × $3,791 = $2,965 EV
    "vwap-break/curl",    # 78.1% × $7,126 = $5,565 EV (highest EV, lower frequency)
    "micro-pullback",     # 74.3% × $3,560 = $2,645 EV
    "vwap-reclaim",       # 72.0% × $6,920 = $4,982 EV
    "opening-range",      # 70.8% × $1,654 = $1,171 EV
    "bull-flag/flat-top", # 69.6% × $2,134 = $1,485 EV
    "halt-resume",        # 68.0% × $654  = $445 EV
    "pullback/dip",       # 64.0% × $1,728 = $1,106 EV
    "whole-dollar-break", # 64.3% × $1,477 = $949 EV
    "continuation",       # 64.6% × $2,308 = $1,491 EV
    "red-to-green",       # 66.2% × $216  = $143 EV (low EV despite ok win rate)
    # --- below threshold: do not enter ---
    "breakout",           # 56.4% — skip unless anchored to named level
    "reverse-split",      # 54.2% — skip
    "abcd",               # 42.9% — disabled
]

IF trigger in TRIGGER_PRIORITY[:10]:
    evaluate entry normally
ELIF trigger == "breakout":
    only enter IF breakout level == premarket_high OR whole_dollar OR opening_range
    # i.e. reclassify to the named anchor, do not enter as generic breakout
ELSE:
    skip

ON conflict (multiple triggers on same symbol):
    use highest-priority trigger from TRIGGER_PRIORITY
    do not stack entries — one trigger per entry
```

---

## Data Confidence

| Field | Coverage | Confidence |
|---|---|---|
| Category classifications | 5,261 trades, all assigned | High |
| Win rate per category | Computed from outcome data | High |
| Avg result per category | Computed from P&L data | High |
| "other" composition | 1,813 trades, partially decomposed via corpus | Medium — squeeze/news/momentum sub-types identified, not win-rated |
| abcd-pattern sample | 14 trades | Low — insufficient sample for precise EV calc |
| opening-range sample | 48 trades | Medium — pattern is correct, narrow CI |
| vwap-break/curl subcategories | Not decomposed | Medium — break vs. curl conflated |
| squeeze sub-trigger win rate | ~41 corpus mentions, no standalone rate | Low — estimate ~70% based on pattern behavior |
| halt-resume sub-variants | 4 sub-types identified from corpus | Medium — counts small per sub-type |
| false breakout entries | 5 corpus mentions | Low — too small for win rate |
| daily breakout isolation | 8 corpus mentions | Low — likely in "breakout" 56.4% bucket |
| sympathy plays | 6 corpus mentions | Low — no win rate |
| raw corpus trigger alignment | 5,091 extracted vs 5,261 RC_STATS | High — ~3% gap from parsing variance |

**Note on "other":** 34% of all trades are unclassified. Corpus analysis identifies squeeze (~41), news-driven (~21), momentum cluster (~115), and sympathy plays (~6) as structured sub-types within "other." If separated, the residual true-"other" (unstructured L2-gut-feel trades) would be a smaller but lower-win-rate bucket. The taxonomy is directionally reliable and corpus-validated.
