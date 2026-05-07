# Concept: Micro Pullback

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md; concept_pattern_playbook.md (FILES 0002, 0027)  
**Sample size:** 350 trades  
**Win rate:** 74.3% | **Avg result:** +$3,560 | **Total P&L:** +$1,246,000

---

## Definition

Micro pullback is a momentum continuation pattern. Stock makes a strong opening move, pulls back 1-3 candles on lower volume, then resumes higher. Entry is on the resumption — either at the prior candle's high or as price breaks above the consolidation.

**Core idea:** In strong momentum, dips are shallow and brief. A 1-3 candle pause with decreasing volume is a rest, not a reversal. The micro pullback entry buys this rest before the next leg up.

---

## Statistical Case

| Category | Trades | Win Rate | Avg Result | Total P&L |
|----------|--------|----------|------------|-----------|
| micro-pullback | 350 | **74.3%** | **+$3,560** | +$1,246,000 |

74.3% win rate = second highest among all main patterns (trailing only gap-and-go). The +$3,560 average is strong for a scalp/short-hold pattern, indicating good risk/reward when the setup is valid.

**Hold type distribution:**
| Hold type | % of trades | Notes |
|-----------|-------------|-------|
| Scalp (1-5 min) | 43.7% | Most common — quick breakout, take profit on extension |
| Short hold (5-30 min) | 36.7% | Second most common |
| Extended (30min+) | 9.3% | Present but not the primary expectation |

---

## Setup Requirements

### Preconditions (stock qualifies if ALL true)
1. **Prior strong momentum move** — stock has already made a significant move up (20%+ gap, early morning run)
2. **Pullback is shallow** — price pulls back only 1-3 candles; NOT a full reversal
3. **Pullback volume decreasing** — the dip candles have lighter volume than the rip candles (sellers not aggressive)
4. **Price holds above EMA-9** — or at minimum, EMA-9 is pointing up and close to price (confirms uptrend intact)
5. **MACD line > 0** — (4.7% relevance, highest of all patterns) — front-side momentum preferred
6. **Time window** — valid before 10:30am; after 10:30 the "micro" in micro-pullback becomes macro and the setup changes

### Entry trigger
- Price breaks above the high of the highest pullback candle
- OR: price reclaims the breakout level that preceded the pullback
- Volume should expand again on the resumption candle (confirms buyers are back)

### Stop placement
- Below the lowest candle of the pullback
- For very tight setups: below EMA-9
- Risk: typically $0.10-0.30 depending on price level

### Target
- T1: Prior high (scale 50% at prior resistance)
- T2: 1R extension (move equal to distance from entry to stop)
- Extended: Trail above EMA-9 if momentum is exceptional

---

## Trade Examples (from playbook)

### FILE 0002 — Sub-1M float, micro-pullback on news
- Stock: sub-1M float, news catalyst
- Setup: strong opening rip, 2-candle pullback, entry on resumption
- **Key characteristic:** Sub-1M float means each share matters more — micro pullback on low float = violent resumption
- **Lesson:** Float affects how fast and how far the resumption moves. Same pattern, 10x the outcome on sub-1M float.

### FILE 0027 — Rapid entries at $3.35 / $3.70 / $3.90
- Multiple micro-pullback entries as stock stair-stepped up
- Each pullback was brief (1-2 candles) then resumed
- Entries at $3.35, added at $3.70, added at $3.90
- **Lesson:** Multiple entries on stair-stepping stock = scale-in strategy. Each micro-pullback is a new entry point on the same thesis.

---

## The "Micro" Definition

**What qualifies as "micro":**
- 1-3 candles
- Price retraces 30-50% of the prior leg (not more)
- Volume drops significantly vs the rip candles (60-70% of rip volume or less)
- Does NOT breach EMA-9 on 1-minute chart (or touches briefly but wicks back above)

**What disqualifies:**
- 4+ candle pullback → becomes a larger consolidation, not micro
- Price breaks below EMA-9 with a candle close → trend weakening
- Volume on pullback candles equals or exceeds volume on rip candles → distribution, not rest
- Price drops more than 50% of the prior leg → too deep, lose the momentum thesis

---

## Time-of-Day Validity

| Window | Quality | Reason |
|--------|---------|--------|
| 9:30-9:45am | Medium | First few candles unpredictable, spread wide |
| 9:45-10:30am | **Best** | Momentum established, pattern most reliable |
| 10:30-11:00am | Low | Morning momentum fading; "micro" becomes "full reversal" |
| 11:00am+ | Skip | Not a valid micro-pullback window |

Ross's rule: "Micro-pullback only works in the first hour. After 10:30, I don't buy dips — I sell them."

---

## Micro Pullback vs Dip Buy

These are related but distinct:

| Pattern | Timing | Setup | Risk |
|---------|--------|-------|------|
| **Micro pullback** | Within an existing momentum move | 1-3 candle rest | Tight stop, high win rate |
| **Dip buy** | After a deeper correction | 3-10 candle consolidation/dip | Wider stop, more judgment required |

Micro pullback is the "rest" during a run. Dip buy is the "recovery" after a bigger setback. If the pullback is deeper than 3 candles or > 50% retracement, it shifts from micro-pullback to dip-buy territory.

---

## MACD Context

**MACD relevance: 4.7%** — highest of all patterns in the data. This is directionally meaningful even if the absolute % is small. For micro-pullback, the front-side signal (MACD Line > 0) provides the most confirmation relative to the pattern structure.

**Why MACD matters more here:** Micro-pullback assumes the stock is still in an uptrend. MACD line > 0 confirms the 12 EMA remains above 26 EMA — i.e., the short-term trend is still bullish. A micro-pullback where MACD line has crossed below zero is a warning sign that the pullback may become a reversal.

**Implementation note:** The dip_buy detector internally requires MACD > 0 (Ross's "3 Tricks"). Micro-pullback should optionally check MACD line > 0 when MACD data is available, especially for add-on entries later in the move.

---

## Float and Micro Pullback

From the data, float size affects micro-pullback outcome significantly:

| Float Range | Win Rate | Avg Result | Notes |
|-------------|----------|------------|-------|
| Sub-1M | Volatile | Large | Violent moves, wide spreads, extreme outcomes |
| 1M-10M | Best risk/reward | ~+$3,560 | Primary target zone for this pattern |
| 10M-50M | Lower | Smaller | Move is slower; less explosive resumption |
| 50M+ | Skip | Too slow | Micro pullback doesn't generate enough momentum |

Ross targets 1M-10M float for micro-pullbacks specifically. Sub-1M is high-risk/high-reward; wider float stocks lack the snap-back velocity that makes the pattern work.

---

## jTrader Implementation Status

`detect_micro_pullback()` in `production/trading/patterns.py`:
- ✅ Checks for prior strong momentum move (high rel_vol, elevated pct_change)
- ✅ Counts pullback candles (1-3 max)
- ✅ Verifies pullback volume is lighter than rip volume
- ✅ Checks EMA-9 proximity (price close to or above EMA-9)
- ✅ Stop below pullback low
- ⚠️ MACD line check optional — requires `enable_macd=True` in EntryConfig (currently disabled by default)

---

## jTrader Decision Rules

```
MICRO_PULLBACK detection:

  Input: bars (1-min), indicators, cfg

  PRIOR MOMENTUM CHECK:
    - look back 5-10 bars, find peak (highest bar in recent history)
    - peak must be significantly above current price (momentum established)
    - avg_volume on rip bars > threshold (was a real move)

  PULLBACK CHECK:
    - bars since peak: 1-3 candles (count red/lower candles from peak)
    - IF bars_since_peak > 3 → no signal (too deep, use dip_buy instead)
    - volume on pullback bars < volume on rip bars * 0.8 (decreasing)
    - current bar close > pullback low (not breaking down)

  EMA-9 CHECK:
    - price close to or above EMA-9 (±0.5% tolerance)
    - EMA-9 pointing up (EMA-9[current] > EMA-9[3 bars ago])

  ENTRY CHECK:
    - current bar breaks above high of pullback
    - OR: current bar close > prior candle high

  IF all pass:
    entry_price = pullback_high + 0.01
    stop_price  = pullback_low - 0.02
    target      = prior_session_high or HOD
    confidence  = 0.74
    RETURN PatternSignal(MICRO_PULLBACK, ...)
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---------|--------|------------|
| Win rate (74.3%) | 350 trades | High |
| MACD highest relevance (4.7%) | 350 trades | Medium |
| Scalp-dominant (43.7%) | 350 trades | High |
| Sub-1M float amplification | Qualitative | Medium |
| 10:30am time cutoff | Qualitative from recaps | Medium |
