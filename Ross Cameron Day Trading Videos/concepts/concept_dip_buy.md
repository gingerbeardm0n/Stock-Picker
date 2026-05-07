# Concept: Dip Buy

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md; concept_pattern_playbook.md (FILES 0005, 0006, 0017)  
**Sample size:** 712 trades (dip-buy) / 944 trades (pullback/dip combined)  
**Win rate:** 64.0% | **Avg result:** +$1,728 | **Total P&L:** +$1,631,232 (combined)

---

## Definition

A dip buy is a counter-trend entry within an uptrend. The stock has made a significant move (50-200%+ gap or intraday run), pulled back significantly (more than a micro-pullback — typically 4-10 candles or 30-60% retracement), and the dip buy entry is placed at a level where buyers are expected to step back in.

Unlike micro-pullback (1-3 candles, minimal retracement), dip buy involves a real correction that tests a key level — premarket support, prior resistance-turned-support, VWAP, or a round number.

---

## Statistical Case

| Category | Trades | Win Rate | Avg Result | Total P&L |
|----------|--------|----------|------------|-----------|
| dip-buy (direct) | 712 | ~64.0% | ~+$1,728 | ~+$1,229,000 |
| pullback/dip (combined) | 944 | **64.0%** | **+$1,728** | +$1,631,232 |

**Lowest win rate of the main patterns at 64%.** However, still significantly profitable due to high trade volume (944 combined) and solid average result.

**Hold type distribution:**
| Hold type | % of trades | Notes |
|-----------|-------------|-------|
| Scalp (1-5 min) | 35.8% | Quick dip-and-rip trades |
| Short hold (5-30 min) | 46.8% | Dominant hold type |
| Extended (30min+) | 6.2% | Present when dip occurs early in session |

---

## Ross's "3 Tricks" for Dip Buy

Ross has specific criteria — he calls them "3 Tricks" — that must all be present for a valid dip buy:

### Trick 1: Stock Must Have Had a Real Catalyst
- News must be present and specific
- Not sector sympathy, not just a gapper
- The catalyst is what will bring buyers back at the dip
- Without catalyst, the dip may not recover (no reason for buyers to step in)

### Trick 2: MACD Line Must Be Positive (Front Side)
- MACD Line (12 EMA - 26 EMA) > 0 on the 1-minute chart
- Front side confirmation: the broader trend is still up
- Back side dip buys = **no trade**
- This is the strongest MACD gate in Ross's system (see `concept_front_side_back_side.md`)
- dip_buy detector in `patterns.py` checks `indicators['macd_line'] > 0` internally

### Trick 3: Clear Support Level to Buy At
- Not buying into random air — buying at a specific reference level
- Valid support levels:
  - Premarket high (former resistance = new support)
  - Prior day's close
  - VWAP (if stock dipped to VWAP and is holding)
  - Round number ($5.00, $10.00, $15.00)
  - EMA-9 on the 5-minute chart (longer-term trend)
  - 50% retracement of morning run
- Entry is placed just above the support level (buy the first green candle above support)

All 3 tricks required. One or two is insufficient — skip the trade.

---

## Trade Examples (from playbook)

### FILE 0005 — Dip at $3.50 premarket, add at $4.00, target $4.40-$4.50
- Stock gapped up, pulled back to $3.50 premarket support
- Initial entry at $3.50 (premarket support = Trick 3)
- Added at $4.00 as stock resumed
- Target $4.40-$4.50 (prior premarket high = T2)
- **Lesson:** Premarket support levels are the most reliable dip-buy targets

### FILE 0006 — Break of $3.50, scale 3K→6K→9K
- Entry at $3.50 breakout (support level)
- Scaled position: 3,000 shares → added to 6,000 → added to 9,000
- Exit on momentum fade
- **Lesson:** Dip buys allow scaling — initial position small, add on confirmation

### FILE 0017 — Full pyramid: 2.5K→5K→7.5K→10K→12.5K→15K→17.5K
- 7-tier position pyramid as stock climbed from dip
- Each add was on a new high or confirmed continuation candle
- Extreme case of scale-in dip buy
- **Lesson:** When the dip-buy thesis is correct and momentum is strong, scaling to 7x initial position is Ross's maximum conviction expression

---

## Dip Buy vs Micro Pullback: Clear Distinction

| | Micro Pullback | Dip Buy |
|---|---|---|
| Candles in pullback | 1-3 | 4-15+ |
| Retracement depth | 20-40% of prior leg | 40-70% of prior leg |
| Volume during dip | Decreasing | Can be heavy (shakeout) |
| EMA-9 | Price holds above | Price may pierce EMA-9 |
| MACD check | Optional (4.7% rel.) | Required (Trick 2) |
| Entry timing | During momentum | After correction |
| Risk | Tight stop | Wider stop needed |

---

## Support Level Hierarchy

When multiple support levels are nearby, prioritize:

1. **Premarket high** — former resistance, most significant technical level
2. **Prior day close** — overnight holding price
3. **VWAP** — volume-weighted mean = fair value for the session
4. **Round number** — psychological support (heavy option strike zone)
5. **50% retracement** — Fibonacci level, widely watched
6. **EMA-9 (5-minute)** — longer-timeframe trend support
7. **EMA-9 (1-minute)** — shortest-term trend support

Buy at the highest-quality level available. Do not buy at the 1-minute EMA-9 if VWAP is nearby — use VWAP.

---

## Why Dip Buy Has Lower Win Rate

64% vs 74.3% (micro-pullback) — the 10pp gap has structural explanations:

1. **More judgment required** — "Is this the dip or is this a reversal?" is genuinely hard to answer
2. **Wider stop necessary** — Support level may be violated briefly before recovering; tight stop = stopped out before the move
3. **Timing imprecision** — Dip can continue lower after entry if support doesn't hold immediately
4. **Back-side risk** — Without the MACD check (Trick 2), dip buys can be front-running a downtrend
5. **Late-session dips** — Dip buys taken after 10:30am on morning momentum stocks are often traps

These are also why the "3 Tricks" exist — they filter the 36% losers out when properly applied.

---

## Scaling Strategy

Dip buy is the primary pattern where Ross scales into positions across multiple entries. The logic:

**Stage 1 (risk-controlled entry):** Small position at the support level. Stop below support. If wrong, small loss.

**Stage 2 (add on confirmation):** When stock resumes from support and makes new highs within the dip, add to position. Stop trail to support level.

**Stage 3 (add on continuation):** If stock breaks above prior resistance, add again. Stop trail to most recent breakout.

**Exit:** Scale out at T1 (prior resistance / morning high), T2 (HOD), trail the rest.

This is Ross's "pyramid" — wider base at support, narrowing position as price extends. Each add requires NEW confirmation, not just hope.

---

## Time-of-Day

| Window | Quality | Notes |
|--------|---------|-------|
| Pre-market (6am-9am) | Good | Premarket dips to support are valid (FILE 0005 example) |
| 9:30-10:00am | High | Opening dip to premarket levels = classic dip buy |
| 10:00-11:00am | Medium | Dips in first hour still valid if momentum was strong |
| 11:00am+ | Low | Late-morning dips often become afternoon breakdowns |
| Premarket only | Special | Pre-open dip to premarket support on heavy volume = tier-1 |

---

## MACD Gate Enforcement

Dip buy is the only pattern where MACD Line > 0 is explicitly required (Trick 2). This is already implemented in `detect_dip_buy()` in `patterns.py`:

```python
# Inside detect_dip_buy() — Trick 2 check
macd_line = indicators.get('macd_line')
if macd_line is not None and macd_line <= 0:
    return None  # Back side — no dip buy
```

This is the correct implementation. When `macd_line` is None (not enough bars, especially at open), the check is skipped — acceptable because early-open dip buys rely on premarket structure rather than MACD.

---

## jTrader Implementation Status

`detect_dip_buy()` in `production/trading/patterns.py`:
- ✅ Requires 3 Tricks (catalyst flag, MACD line > 0, support level)
- ✅ Checks for support level proximity (premarket high, VWAP, round numbers)
- ✅ Requires dip of 4+ candles before entry (distinguishes from micro-pullback)
- ✅ Entry on first green candle above support
- ✅ Stop below support level
- ⚠️ Scale-in logic not automated — initial position only; adds require manual override or separate signal

---

## jTrader Decision Rules

```
DIP_BUY detection:

  Input: bars (1-min), indicators, cfg

  TRICK 1: CATALYST
    - news_catalyst_present = indicators.get('has_news', False)
    - IF NOT news_catalyst_present → no signal

  TRICK 2: MACD FRONT SIDE
    - macd_line = indicators.get('macd_line')
    - IF macd_line is not None AND macd_line <= 0 → no signal

  TRICK 3: SUPPORT LEVEL
    - Compute candidate levels (in priority order):
        premarket_high = indicators.get('premarket_high')
        vwap           = indicators.get('vwap')
        round_numbers  = [floor(current_price), round_half(current_price)]
    - Find nearest level below current price within 3% range
    - IF no level found → no signal
    - support_level = nearest_level

  DIP CONFIRMATION:
    - bars_in_dip = count candles since prior high that are below support_high_threshold
    - IF bars_in_dip < 4 → use detect_micro_pullback() instead
    - current_bar['close'] > support_level   ← candle closed above support
    - current_bar['close'] > current_bar['open']  ← green candle

  IF all pass:
    entry_price = current_bar['high'] + 0.01
    stop_price  = support_level - 0.03
    target_1    = prior_high (morning high)
    target_2    = HOD or 1.5R
    confidence  = 0.64
    RETURN PatternSignal(DIP_BUY, ...)
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---------|--------|------------|
| Win rate (64.0%) | 944 trades | High |
| 3 Tricks framework | Qualitative from recaps | High (repeated across many sessions) |
| MACD Line required (Trick 2) | Direct Ross statement | High |
| Support level hierarchy | Qualitative | Medium |
| Scaling strategy (pyramid) | Repeated in examples | High |
| Time-of-day cutoff (11am) | Qualitative | Medium |
