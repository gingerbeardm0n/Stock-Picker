# Concept: Halt and Resume

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md; concept_pattern_playbook.md (FILES 0008, 0016, 0026)  
**Sample size:** 428 trades  
**Win rate:** 68.0% | **Avg result:** +$654 | **Total P&L:** +$280,312

---

## Definition

A halt-and-resume trade is entered when a stock resumes trading after a regulatory or circuit-breaker halt. During the halt, price discovery is suspended and order books build up on both sides. On resume, the first print sets a new reference price — and the direction of that print determines whether longs or shorts win.

Ross trades two methods:
1. **Aggressive:** Buy the ask immediately on resume
2. **Safer:** Wait for first dip after resume, buy the dip

The halt itself is not the trade — the *resume* is. And within the resume, the first few seconds to first minute are critical.

---

## Statistical Case

| Category | Trades | Win Rate | Avg Result | Total P&L |
|----------|--------|----------|------------|-----------|
| halt-resume | 428 | **68.0%** | **+$654** | +$280,312 |

**Important context:** 68% win rate with $654 avg = good win rate but smallest average result of the main patterns. This reflects the pattern's nature: many small wins, occasional larger wins, with outsized risks on halts that resume poorly.

**Hold type distribution:**
| Hold type | % of trades | Notes |
|-----------|-------------|-------|
| Scalp (1-5 min) | 35.7% | Most halt trades are taken quickly |
| Short hold (5-30 min) | 46.4% | Primary hold window |
| Extended (30min+) | 7.5% | Rare but present on big catalyst halts |

---

## Halt Types

Not all halts are equal. Understanding the halt type before it resumes is critical:

### Circuit Breaker Halt (LULD — Limit Up / Limit Down)
- **Triggered when:** Price moves 5-20% in 5 minutes beyond circuit breaker bands
- **Duration:** 5 minutes, then reopens via auction
- **Context:** Usually happens mid-move on a hot stock
- **Trade quality:** Best. Circuit breaker = the move was real and violent. Resume often continues.
- **Data:** This is the dominant halt type in Ross's halt-resume trades

### News-Pending Halt
- **Triggered when:** Company requests a halt to release material news
- **Duration:** Variable (minutes to hours)
- **Context:** Stock halted before a press release, FDA decision, or major announcement
- **Trade quality:** High variance. If news is good → strong upside. If neutral/bad → violent drop.
- **Risk note:** Cannot trade until news is known. Don't hold through the halt open blind.

### Volatility Pause
- **Triggered when:** Short-term price volatility exceeds exchange thresholds (shorter than LULD)
- **Duration:** 1-5 minutes
- **Context:** Usually on already-moving stock
- **Trade quality:** Similar to circuit breaker but smaller scale

### Regulatory / SEC Halt
- **Duration:** Hours to days
- **Trade quality:** DO NOT TRADE. Regulatory halts indicate serious issues. Cannot predict resume direction.

---

## Two Entry Methods

### Method 1: Aggressive (Buy Ask on Resume)
- As soon as halt lifts and first print appears, buy immediately
- **Advantage:** Captures entire move from resume
- **Disadvantage:** High spread, can't see where price opens, risk of buying into a dump
- **When to use:** Strong circuit breaker halts during violent upward momentum; you saw the move, halt confirms it
- **Risk management:** Tight stop — if first 2-3 bars go red after resume, exit immediately

### Method 2: Safer (First Dip After Resume)
- Wait for price to establish a post-resume range (5-10 seconds to first minute)
- Buy the first pullback toward the initial resume print
- **Advantage:** Confirmation of direction, tighter stop, know where "wrong" is
- **Disadvantage:** Miss some of the initial move
- **When to use:** When uncertain about resume direction; when the halt lasted > 30 minutes

Ross prefers Method 2 for most situations except very high-conviction setups.

---

## Trade Examples (from playbook)

### FILE 0008 — Dip entry after halt, target $5.88-$5.94
- Stock halted during momentum run
- On resume: waited for first dip, entered below resume high
- Target $5.88-$5.94 (prior halt level)
- **Lesson:** Target the halt price — stocks often retest the level that caused the halt

### FILE 0016 — Circuit breaker halt, target $2.10
- Classic LULD circuit breaker during morning move
- Resume entry, target set at next round number ($2.10) above halt price
- **Lesson:** After circuit breaker, next round numbers become magnets because retail attention is highest

### FILE 0026 — Halt resume rip, target $10
- High-profile halt (large % move, significant catalyst)
- Post-resume, stock ripped toward $10 psychological level
- Extended hold warranted by momentum
- **Lesson:** When halt resumes and immediately rips (no dip), first 30 seconds can be Method 1 window

---

## Key Rules for Halt Trades

1. **Know the halt type before resume** — Circuit breaker and news halts trade differently
2. **Watch the bid-ask spread on resume** — Wide spread = market uncertainty = wait for it to tighten
3. **First print tells you direction** — If first print is above prior close, lean long. If below, skip.
4. **Target the halt price** — Price often gravitates back toward the level that triggered the halt
5. **Circuit breakers in uptrends = buy** — If stock was ripping and hit LULD, the resume is often another rip
6. **Do not hold through regulatory/SEC halts** — Exit before, not after
7. **The longer the halt, the less predictable the resume** — 5-minute circuit breaker: predictable. 3-hour news halt: high variance.

---

## Why Halt-Resume Has Lower Average than Other Patterns

$654 average vs $3,560 (micro-pullback) or $6,920 (VWAP reclaim) — significant gap. Reasons:

1. **Short hold dominant (46.4%)** — Positions are frequently exited in first 5-30 minutes; not extended
2. **Wide spreads at resume** — Entry is at a markup, reducing net result even on winners
3. **Occasional large losers** — When a halt resumes poorly (news is bad, or it's a news-pending that went wrong), losses can be significant
4. **High trade volume (428 trades)** — Many small halt trades throughout 1,787 sessions; average diluted by the large number of small scalps

Despite the lower average, 68% win rate means it's a net-positive pattern. The key is position sizing appropriately for the higher variance.

---

## Time-of-Day Considerations

| Window | Quality | Notes |
|--------|---------|-------|
| 9:30-10:00am | **Best** | Morning circuit breakers on gappers have highest follow-through |
| 10:00-11:00am | Good | Late-morning halts still tradeable if momentum present |
| 11:00am+ | Reduced | Afternoon halts on morning runners often fake-out; trend may be reversing |
| Pre-market | Special case | Only trade if halt resumes with volume; pre-market resumes are thin |

---

## Halt as Confirmation Signal

Counterintuitive insight: **a circuit breaker halt is bullish confirmation** in the context of a momentum trade.

When a stock you're watching (or already in) hits a circuit breaker:
- The halt confirms the move was real (strong enough to trigger exchange safeguards)
- Institutional computers that were shorting the move are forced to pause
- Retail traders who were panicking into the move now have 5 minutes to compose themselves and re-buy

Ross has noted: "When I'm in a stock and it halts, that's not a bad thing. Usually it resumes higher."

---

## jTrader Implementation Notes

Halt-resume detection requires:
1. **Halt event detection** — Alpaca WebSocket / market data feed signals halt status
2. **Resume detection** — First bar after resume = entry window
3. **Pre-resume state** — Track the price before halt to assess momentum direction
4. **Method selection** — Default to Method 2 (first dip); Method 1 only if momentum is strong and halt < 10 min

Current status: Not yet implemented in patterns.py. Requires market data feed integration to detect halt/resume events in real time. In simulation, halt detection requires scanning for bars with extreme volume + price jumps between consecutive bars.

---

## jTrader Decision Rules

```
HALT_RESUME detection:

  Input: bars (1-min), real-time halt event (from market feed)

  HALT DETECTION:
    - market_feed.is_halted(symbol) == True
    - halt_type in ['LULD', 'CIRCUIT_BREAKER'] (not regulatory)
    - pre_halt_trend: bars[-5:] were trending up (price was rising)

  ON RESUME:
    - resume_bar = first bar after halt
    - IF resume_bar['close'] > resume_bar['open']:    ← green on resume
        METHOD = 'AGGRESSIVE' if halt_duration < 10min AND prior_trend_strong
                 'SAFER' otherwise

  AGGRESSIVE entry:
    entry_price = resume_bar['high'] + 0.01
    stop_price  = resume_bar['low'] - 0.02

  SAFER entry (Method 2):
    wait for first pullback after resume
    IF price dips to resume_bar['open'] area on low volume:
      entry_price = dip_low + 0.01
      stop_price  = below dip low

  target = prior_halt_price (level that triggered halt)
         OR next round number above entry
  confidence = 0.68
  RETURN PatternSignal(HALT_RESUME, ...)
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---------|--------|------------|
| Win rate (68.0%) | 428 trades | High |
| Avg result (+$654) | 428 trades | High |
| Short-hold dominant (46.4%) | 428 trades | High |
| Circuit breaker = bullish confirmation | Qualitative | Medium |
| Method 1 vs Method 2 outcomes | Not directly measured | Low |
| Two-method framework | Qualitative from recaps | High |
