# Concept: Entry Trigger Taxonomy

**Last updated:** 2026-05-07
**Source:** RC_STRATEGY_STATISTICS.md Section 3; concept_pattern_playbook.md
**Sample size:** 5,261 trades across 1,787 sessions
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

### ABCD is dead

14 trades, 42.9%. Disabled in jTrader after Trial 193. The data confirms the optimizer found the correct answer. ABCD's A-to-C structure introduces too much timing noise for low-float momentum stocks.

### "other" is the slippage bucket

1,813 trades at 60.5% — Ross's non-rule trades. He reads L2, feels market temperature, reacts to news. These trades collectively underperform his named patterns (64.8% overall). Automating the named patterns and skipping unclassified triggers is the right architecture choice.

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
| "other" composition | 1,813 trades, unclassified | Low — heterogeneous bucket |
| abcd-pattern sample | 14 trades | Low — insufficient sample for precise EV calc |
| opening-range sample | 48 trades | Medium — pattern is correct, narrow CI |
| vwap-break/curl subcategories | Not decomposed | Medium — break vs. curl conflated |

**Note on "other":** 34% of all trades are unclassified. If Pass 2 or Pass 3 enrichment reclassifies even 20% of the "other" bucket into named categories, win rate estimates across all tiers will shift. The current taxonomy is directionally reliable but not final.
