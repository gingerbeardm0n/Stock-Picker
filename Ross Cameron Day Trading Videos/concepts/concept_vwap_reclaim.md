# Concept: VWAP Reclaim

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md; concept_pattern_playbook.md (FILES 0019, 0308, 0348)  
**Sample size:** 50 trades (vwap-reclaim) + 137 trades (vwap-break/curl) = 187 combined  
**Win rate:** 72.0% (vwap-reclaim) / 78.1% (vwap-break/curl) | **Avg result:** +$6,920 / +$7,126

---

## Definition

VWAP Reclaim is a momentum continuation pattern. Stock dips below VWAP intraday, then reclaims it with a decisive 1-minute candle closing above VWAP on elevated volume. The reclaim signals that buyers have stepped back in and price is returning to trend.

**Key distinction from other patterns:** VWAP Reclaim is a *recovery* play — you're buying into a stock that showed strength (gap, news, big move), dipped to test VWAP, and is now resuming. You're not buying the first move; you're buying the confirmation of trend continuation.

---

## Statistical Case

| Category | Trades | Win Rate | Avg Result | Total P&L |
|----------|--------|----------|------------|-----------|
| vwap-reclaim | 50 | **72.0%** | **+$6,920** | +$311,421 |
| vwap-break/curl | 137 | **78.1%** | **+$7,126** | +$976,261 |

**Highest average result of all non-halt patterns.** The $6,920-$7,126 per-trade average is approximately 2x the next best pattern (gap-and-go at ~$4,000+). This reflects the extended hold category being highest of all patterns.

**Extended hold %:** 11.8% — highest of all patterns. VWAP reclaim stocks are the ones that run all day.

| Hold type | % of trades | Notes |
|-----------|-------------|-------|
| Scalp (1-5 min) | 25.5% | Quick reclaim, immediate fade — take T1 fast |
| Short hold (5-30 min) | 43.8% | Primary hold type for this pattern |
| Extended (30min-EOD) | 11.8% | **Highest of all patterns** — these become multi-hour runners |

---

## Setup Requirements

### Preconditions (stock qualifies if ALL true)
1. **News catalyst present** — VWAP reclaims on no catalyst are tier-3; news-driven reclaims are tier-1
2. **Stock gapped up or made a significant morning run** — VWAP below current price structure means it had momentum first
3. **Price tested VWAP** — at least 1 bar closed below VWAP (confirmed test, not just touch)
4. **Volume on reclaim candle ≥ 1.2× avg** — buyers returning with conviction, not just drift back above

### Entry trigger
- 1-minute candle **closes above VWAP** on elevated volume
- Previous 1-5 candles were at or below VWAP (confirmed the test)
- Entry = breakout above the reclaim candle's high OR at close of reclaim candle

### Stop placement
- **Below VWAP** — if price drops back below VWAP after entry, the reclaim failed
- Tight stop: 1-3 cents below VWAP at entry time
- Wide stop: below the lowest candle of the VWAP test (more room, smaller size)

### Target
- T1: Prior resistance or morning high (scale 50%)
- T2: New high of day / prior high of day
- Extended: Trail stops above VWAP, hold as long as price holds above

---

## Trade Examples (from playbook)

### FILE 0019 — VWAP break → halt → squeeze → extended hold
- Stock had big premarket move, broke VWAP intraday, halted
- On resume: bought the dip back toward VWAP, target "above $10"
- Outcome: multi-dollar extended run
- **Lesson:** Halt-resume combined with VWAP reclaim = highest-quality entry (both catalysts present)

### FILE 0308 — News pop, curl back to VWAP, 7am entry
- Pre-open: stock up on news, pulled back to VWAP area
- Entry at 7am premarket as price curled back up from VWAP
- Target $4.84 (prior premarket resistance)
- **Lesson:** VWAP reclaim works premarket if stock has sufficient volume structure

### FILE 0348 — 180% gap, add-on at move
- Stock gapped 180%, pulled back to VWAP, reclaimed
- Initial entry on reclaim, added on continuation move
- Target $6.18
- **Lesson:** High-gap stocks (100%+) often have violent VWAP tests — the reclaim when it comes is extremely strong signal

---

## Why VWAP Reclaim Works

VWAP is a volume-weighted mean price for the session. When a stock dips below VWAP:
- Sellers temporarily took control
- Longs who bought below VWAP are now sitting on paper gains when price reclaims
- Short sellers who shorted at VWAP are squeezed when price reclaims

The reclaim candle represents a capitulation of the short side + re-entry of longs. Combined, this creates a powerful directional move. The longer and more decisive the reclaim candle (high volume, large body), the stronger the continuation.

---

## VWAP Reclaim vs VWAP Break/Curl

These are related but distinct:

| Type | Setup | Entry timing |
|------|-------|-------------|
| **VWAP Reclaim** | Dip below VWAP → candle closes back above | Entry on close or breakout of reclaim candle |
| **VWAP Break/Curl** | Price curling up to test VWAP from below | Earlier entry — anticipate the reclaim |

Break/curl has slightly higher win rate (78.1% vs 72.0%) because it catches the move before confirmation — but requires more judgment. Reclaim is more mechanical and thus more automatable.

**jTrader implements:** VWAP Reclaim (confirmation-based). Break/curl would require prediction rather than confirmation.

---

## Time-of-Day Considerations

| Window | Quality | Notes |
|--------|---------|-------|
| 9:30-10:00am | Low | Not enough bars for reliable VWAP; first test is often violent and immediate |
| 10:00-11:00am | High | Best window — price has established morning trend, VWAP has meaningful data |
| 11:00am-12:00pm | Medium | Liquidity drops, but strong movers still valid |
| 12:00pm+ | Low | Afternoon VWAP tests on morning runners often don't hold |

---

## MACD Context

**MACD relevance for VWAP Reclaim:** Low (2.6% per RC_STRATEGY_STATISTICS.md). Price action signal dominates — a clean VWAP reclaim with volume is sufficient without MACD confirmation.

**Do NOT require MACD > 0 for VWAP reclaim entry.** The pattern inherently contains the front-side signal (stock reclaiming VWAP = price trending up again). Requiring MACD confirmation would filter out early reclaims where 12 EMA hasn't yet crossed 26 EMA.

---

## jTrader Implementation Status

`detect_vwap_reclaim()` in `production/trading/patterns.py`:
- ✅ Checks recent bars for VWAP test (at least `vwap_reclaim_min_below` bars below VWAP)
- ✅ Requires current bar to close above VWAP on elevated volume (≥ `vwap_reclaim_breakout_vol_min` × avg)
- ✅ Stop set below VWAP
- ✅ VWAP calculated in `entry_engine._calculate_vwap()` (9:30am+ bars only)

**Config defaults** (`EntryConfig`):
```python
enable_vwap_reclaim: bool = True
vwap_reclaim_lookback: int = 5       # bars to look back for VWAP test
vwap_reclaim_min_below: int = 1      # min bars that must be below VWAP
vwap_reclaim_breakout_vol_min: float = 1.2  # volume multiplier for reclaim bar
```

---

## jTrader Decision Rules

```
VWAP_RECLAIM detection:

  Input: bars (1-min), indicators['vwap'], cfg

  PRECONDITIONS:
    - len(bars) >= cfg.vwap_reclaim_lookback + 1
    - indicators['vwap'] is not None

  VWAP TEST CHECK:
    - look back cfg.vwap_reclaim_lookback bars
    - count bars where bar['low'] < vwap
    - IF count < cfg.vwap_reclaim_min_below → no signal

  RECLAIM CHECK (current bar):
    - current_bar['close'] > vwap                    ← price closed above VWAP
    - current_bar['close'] > current_bar['open']     ← green candle
    - current_bar['volume'] >= avg_volume * vwap_reclaim_breakout_vol_min

  IF all pass:
    entry_price = current_bar['high'] + 0.01    ← buy breakout of reclaim bar
    stop_price  = vwap - 0.02                  ← just below VWAP
    target      = next_resistance or HOD
    confidence  = 0.72                         ← based on win rate
    RETURN PatternSignal(VWAP_RECLAIM, ...)
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---------|--------|------------|
| Win rate (72.0%) | 50 trades | Medium (small sample) |
| vwap-break/curl win rate (78.1%) | 137 trades | High |
| Extended hold % highest of all patterns | 50+137 trades | High |
| MACD relevance low (2.6%) | 50 trades | Medium |
| Entry trigger (close above VWAP + volume) | Qualitative from examples | High |
