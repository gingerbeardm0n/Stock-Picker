# Concept: Gap and Go

**Last updated:** 2026-05-06  
**Source:** Pass 1 enrichment of FILES 0001-1799 (9,902 trade rows)  
**Sample size:** 1,177 gap-and-go trades (23% of all 5,010 parsed trades — most frequent pattern)  
**Win rate:** 69% (812W / 338L of 1,165 trades with outcome data)

---

## Definition

Gap-and-go is Ross's highest-frequency setup. A stock gaps up significantly premarket on a catalyst (news, earnings, halt-resume), holds above VWAP or premarket support, and continues the momentum move at or near the open. The entry is the break of the premarket high — not a pullback, not a dip buy — the continuation of upward momentum.

Key distinction from other patterns:
- **vs. micro-pullback:** gap-and-go enters on the BREAK, micro-pullback enters on the DIP after the initial move
- **vs. halt-resume:** gap-and-go is news-driven at open, halt-resume occurs mid-session after a circuit breaker halt
- **vs. red-to-green:** gap-and-go stays green all day; red-to-green recovers from negative territory

---

## Setup Criteria

### Required
| Criterion | Target | Notes |
|-----------|--------|-------|
| Gap% | 20%+ preferred; 40-300%+ ideal | 100%, 50%, 40%, 35% are most common in sample |
| News catalyst | Required | AI announcement, biotech data, earnings beat, sympathy play |
| Premarket volume | High/very-high | "High" = 82% of rel_vol values when populated |
| Float | Low preferred (sub-1M to 4M) | Low float = bigger moves per share |
| Price level | Stock holding above VWAP or prior-day high | Weak holds = skip |

### Ideal (increases conviction)
- Premarket high is a clean, obvious level (whole dollar, half dollar)
- Multiple attempts to break premarket high (consolidation = coiled)
- Sector sympathy plays also moving (confirms sector momentum)
- Day is "hot market" (Ross explicitly scales aggression on hot days)

---

## Entry Trigger

**Primary trigger:** Break of premarket high  
(Appears in top entry trigger variants across the sample: "break premarket high", "break of premarket high", "premarket high break", "gap-and-go / break of premarket high")

**Mechanism:**
1. Identify the premarket high on the chart
2. Wait for price to consolidate near that level (micro-pullback or flat base)
3. Enter on the CANDLE that breaks and holds above premarket high
4. Confirm with volume — the break should come on increased tape activity

**Time of entry:** Open-biased
- 9:30am: most common explicit time
- "Premarket" / "pre-market" entries also frequent (8am-9:29am)
- Avoid gap-and-go setups after 10:30am — momentum windows close

---

## Add-On Mechanics

Based on 1,177 trades, most common add-on approaches:

| Mechanic | Frequency | Description |
|----------|-----------|-------------|
| Scaling | Most common | Add shares as price proves the move (adds at breakout levels) |
| Adds on dips | Common | Small pullbacks mid-move are re-entry opportunities |
| Multiple adds | Common | Ross scales in $3K→$6K→$9K style as conviction builds |
| Quick scalp (no adds) | ~15% | Pure scalp with no adds — smaller size, faster exit |

**Key principle:** Ross sizes INTO strength, not against it. If the move stalls, he stops adding.

---

## Stop Criteria

| Stop Type | Frequency | When to Apply |
|-----------|-----------|---------------|
| Failed breakout | Most common | Price breaks premarket high, immediately reverses below it — hard stop |
| Reversal | Common | Tape flips from buying to selling pressure — scale out |
| Below VWAP | Moderate | VWAP reclaim fails — exit partial or full |
| Halt-down | Occasional | Circuit breaker halt to downside — exit all on resume |

**Stop placement:** Below the premarket high level that was broken (the trigger level becomes support). If price reclaims, Ross will often re-enter.

**Critical rule from summaries:** Ross holds through SMALL flushes if the overall structure is intact, but exits immediately on failed breakouts that close back below the breakout level. The wick of FILE 1017 (MSGM: unrealized -$17K) shows the risk of holding too long.

---

## Profit Targets

| Target Type | Notes |
|-------------|-------|
| Whole-dollar levels | $2.00, $3.00, $4.00, $5.00 — key resistance levels |
| Half-dollar levels | $4.50, $7.50, $8.50 — secondary targets |
| Resistance from chart | Prior highs, pre-break consolidation zones |
| Scaling exits | Ross rarely takes a single exit — scales out 25-50% at each target |

**Observed T1 values:** $4.20, $7.50, $8.00+, $6.50, $3.50, $5.00+, $14.00, $11.00, $4.90 — spread suggests these are stock-specific, not fixed levels.

---

## Hold Duration

| Duration | % of gap-and-go trades |
|----------|------------------------|
| Short (5-30 min) | 48% |
| Scalp (<5 min) | 38% |
| Extended (30min+) | 10% |
| Unknown | 4% |

**Interpretation:** Gap-and-go is primarily a short-term setup. Ross takes quick profits when momentum is obvious, extending hold time only when the stock has exceptional relative strength. Extended holds (10%) likely correspond to the $30K-$50K+ days in the sample.

---

## MACD State

MACD state is **rarely documented** for gap-and-go entries:
- Unknown: 66%
- Not populated (-): 30%  
- Positive: 4%
- Negative: <1%

**Interpretation:** Ross does not use MACD as a primary filter for gap-and-go. The setup is momentum/news-driven. MACD being positive is a bonus, not a requirement.

---

## Market Temperature Dependency

Gap-and-go performance is strongly correlated with market temperature (hot vs. cold day):

From summaries:
- **Hot days:** Ross enters larger size, adds more aggressively, holds longer (FILE 1307: "fourth week of strong momentum" → $5,200 day with multiple winners)
- **Cold days:** Same stocks, same setup, but stops hit more frequently; Ross size-reduces
- **Rule:** On cold days, skip borderline gap-and-go setups. Only take the A+ catalyst with highest premarket volume.

---

## Red Flags (When to Skip)

- Gap is small (<15%) or driven by unclear news
- Premarket volume is low relative to float
- Stock already ran 2x+ premarket and has no fresh catalyst at open
- Level 2 shows heavy sellers stacked at premarket high (resistance won't break cleanly)
- Broad market is down (indices red) — gap-and-go setups fail more frequently
- Stock is a large-float name (>10M shares) — moves are slower, harder to scalp
- After 10:30am — morning momentum has decayed

---

## Example Trades (from chunk files)

**FILE 1444 — VXRT (archetypal setup):**  
Gapped to premarket high of $4.90, pulled to $3.50, curled back. Ross entered 9,000 shares at $4.50 on the half-dollar break. Scaled from $4.50 to $6.00 for ~$5,000 net. Classic: catalyst, low float, clean premarket high, half-dollar entry trigger.

**FILE 0309 — AUD (news-driven extension):**  
AI announcement at 7am moved stock $1.50 → $3.00 premarket. Ross entered $2.26, scaled out $2.78-$2.82 for $3,000 gain. Demonstrates premarket gap-and-go (not waiting for open when catalyst is strong enough).

**FILE 1515 — CLRO ($43K winner):**  
Moved $13 → $19 on news with multiple pullback scalps. $43,000 winner on extended hold. Represents the upside when gap-and-go extends into a full trend day.

**FILE 1017 — MSGM (cautionary tale):**  
Leading gapper at $45 premarket. Three rapid entries starting 7:00am. Caught $7 flush, briefly -$17,000 unrealized. Held through — recovered — but demonstrates risk of early premarket entries on high-priced stocks with thin tape.

---

## jTrader Decision Rules

Based on the above analysis, these are the concrete rules jTrader should apply:

```
GAP_AND_GO entry conditions:
  - gap% >= 20% (prefer >= 40%)
  - has news catalyst
  - premarket relative volume = HIGH or VERY_HIGH
  - price approaching or at premarket high
  - time < 10:30am ET
  
  IF float < 5M:
    allow larger position (up to max_position_pct)
  ELSE:
    reduce size by 50%

Entry trigger:
  - 1m candle CLOSES above premarket high
  - volume on that candle > 1.5x average candle volume

Stop:
  - initial stop = below premarket high (the broken level)
  - if price closes back below trigger = full exit

Targets:
  - T1 = next whole or half dollar above entry
  - scale 25-33% at T1, hold rest
  - T2 = next significant resistance or +50% from entry

Hold:
  - default = short (5-30 min)
  - extend only if stock is making new highs on strong volume
  - exit all by 10:30am unless extended (30min+) conviction

Market temperature gate:
  - hot market: normal size
  - cold market: 50% size, A+ setups only
```

---

## Data Confidence

| Field | Coverage | Confidence |
|-------|----------|------------|
| PATTERN_TYPE (gap-and-go) | 1,177 trades confirmed | High |
| ENTRY_TRIGGER | ~12% explicit, rest inferred | Medium |
| HOLD_DURATION | 96% populated | High |
| GAP% | 17% populated | Low (use as directional, not precise) |
| FLOAT | 6% populated | Low (use as directional, not precise) |
| MACD_STATE | 4% positive, rest unknown | N/A — not a reliable filter |

**Pass 2 opportunity:** Re-reading transcripts for the top 50 gap-and-go files (by trade count) would significantly improve GAP%, FLOAT, and ENTRY_TRIGGER coverage.
