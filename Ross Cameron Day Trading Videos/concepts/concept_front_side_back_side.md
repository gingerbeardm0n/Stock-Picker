# Concept: Front Side vs Back Side (MACD Framework)

**Last updated:** 2026-05-21  
**Source:** RC_STRATEGY_STATISTICS.md (5,010 trades, pattern-MACD correlations); jTrader_Audit_Against_Statistics.md rule #38; TRANSCRIPT_SUMMARIES_0001-1799 corpus (MACD_STATE field: 391 coded entries, 390 = "unknown" — field sparsely populated; qualitative evidence from session narratives is primary corpus source)  
**Core rule:** MACD LINE > 0 = front side = valid trade. MACD LINE ≤ 0 = back side = no trade.

---

## Definition

The front side / back side framework is Ross Cameron's primary MACD-based filter. It determines whether a stock is in an upward momentum phase (front side) or has rolled over and is declining (back side).

**Front side:** Stock is making new highs, MACD line is above zero, buyers are in control.  
**Back side:** Stock has peaked and is losing momentum, MACD line has crossed below zero, sellers are regaining control.

The rule is binary and non-negotiable in Ross's system: **back-side trades are not taken, period.**

---

## The MACD Line vs MACD Histogram Distinction

This is the most common implementation mistake — the two are different signals:

| Signal | Calculation | What it measures |
|--------|-------------|-----------------|
| **MACD Line** | 12 EMA − 26 EMA | Absolute momentum direction — is price trending up overall? |
| **MACD Histogram** | MACD Line − Signal Line (9 EMA of MACD) | Rate of change of momentum — is momentum accelerating or decelerating? |

**Ross uses the MACD LINE, not the histogram.**

- MACD Line > 0 → 12-period EMA is above 26-period EMA → price is trending up → front side
- MACD Line ≤ 0 → 12-period EMA has crossed below 26-period EMA → price is trending down → back side

The histogram crossing zero is a different (later) signal — it means the MACD Line is moving away from its signal line, which is a momentum acceleration signal. Useful for exits (see `concept_stop_management.md`) but NOT the front/back-side gate.

**jTrader bug:** `entry_engine.py` currently checks `macd_histogram <= 0` — this is the wrong signal. Even if `enable_macd` were set to `True`, it would be checking the wrong thing.

---

## Why MACD Line > 0 Matters

On a 1-minute chart at 9:30am:

```
Front side scenario:
  - Stock gaps up 50% premarket
  - Open: 12 EMA > 26 EMA (both EMAs are rising, short > long = positive)
  - MACD Line = +0.45 (positive)
  - Price making new highs relative to prior session
  - Momentum is building, not decaying
  → VALID TRADE

Back side scenario:
  - Stock gapped up yesterday, already down from high today
  - 12 EMA has crossed below 26 EMA
  - MACD Line = -0.12 (negative)
  - Price below VWAP, momentum decaying
  - Buyers have stepped back
  → NO TRADE — back side, skip regardless of how tempting
```

---

## Front Side Characteristics

A front-side trade has ALL of the following:

1. **MACD Line > 0** on the 1-minute chart (12 EMA > 26 EMA)
2. **Price making new highs** — successive 1-minute candle highs are higher
3. **Volume on up-bars** exceeds volume on down-bars (buying pressure dominant)
4. **Price above VWAP** (front side stocks generally hold above VWAP at entry)
5. **EMA-9 pointing up** — short-term trend aligns with MACD signal

When all 5 are true, the stock is in confirmed front-side momentum. This is the ideal entry environment.

---

## Back Side Warning Signs

Any of these signal back-side risk:

- MACD Line crosses below zero (definitive back side)
- Price making lower highs on the 1-minute chart
- Volume drying up on green candles but expanding on red candles
- Price below VWAP and failing to reclaim
- EMA-9 curling down (short-term trend weakening)
- Stock already ran 100%+ from open with no fresh catalyst — exhaustion, not momentum

**Key rule:** A stock that "looks like" a breakout on back side will fail. The same chart pattern (flat top, micro-pullback) that works on front side will fail on back side because buyers are no longer stepping up.

---

## MACD Line on Different Timeframes

Ross uses this primarily on the 1-minute chart. The signal is timeframe-specific:

| Timeframe | MACD Line > 0 context | When to use |
|-----------|----------------------|-------------|
| 1-minute | Is the intraday trend up? | Entry gate (primary use) |
| 5-minute | Is the morning session trending up? | Confirmation / add-on context |
| Daily | Is this a multi-day runner? | Pre-screen for extended holds |

For gap-and-go trades at the open, the 1-minute MACD may not yet be computable (need 26+ bars). In that case, the premarket chart and the opening candle direction serve as the proxy. If the first candle of the open is green with high volume, the stock is on front side — proceed.

---

## MACD and Pattern Interaction

Different patterns have different MACD relevance:

| Pattern | MACD Required? | Notes |
|---------|----------------|-------|
| Gap-and-go | No (3.7% MACD rel) | Momentum/news driven; first 15 bars often lack MACD data |
| VWAP-reclaim | No (2.6%) | Price action signal dominates |
| Micro-pullback | Low (4.7%) | Front-side assumption baked into pattern structure |
| Dip-buy | Yes (4.4% + Ross's "3 Tricks") | MACD positive is Trick 2 of the 3 Tricks |
| Flat-top / Bull-flag | No (1.2% / 0%) | Consolidation patterns don't require MACD check |

**Conclusion:** MACD gate applies most critically to **dip-buy** (already enforced inside `detect_dip_buy()`). For gap-and-go and VWAP-reclaim, MACD should NOT be a blanket gate — the patterns are momentum-driven and entered too early in the session for reliable MACD data.

The current `enable_macd = False` default in `EntryConfig` is approximately correct in effect — but the reason should be that it's pattern-specific, not that it's disabled globally.

---

## MACD as an Exit Signal

Separate from the entry gate, MACD histogram is useful on exits:

- MACD histogram **crossing from positive to negative** while in a profitable trade → momentum reversing → scale out or tighten stop
- This is the `enable_macd_flip_exit` flag in `ExitConfig` (currently disabled)

See `concept_stop_management.md` for exit context. The front-side framework applies to entries; MACD histogram flip applies to exits.

---

## Implementation Correction Required

Current `entry_engine.py` Gate 3 (if ever enabled):
```python
# WRONG — checks histogram, not MACD line
if ecfg.enable_macd and macd_data is not None and indicators['macd_histogram'] <= 0:
    return None
```

Correct implementation:
```python
# CORRECT — checks MACD line (12 EMA - 26 EMA)
macd_line = macd_data['macd_line'] if macd_data else None  # 12 EMA - 26 EMA
if ecfg.enable_macd and macd_line is not None and macd_line <= 0:
    return None
```

The `calculate_macd()` function in `indicators.py` needs to return `macd_line` (not just histogram). Verify `macd_data` dict has a `'macd_line'` key; if not, add it.

Additionally, the MACD gate should be **pattern-aware** — skip the check for gap-and-go and VWAP-reclaim, apply it for dip-buy (already handled internally) and optionally for micro-pullback add-ons.

---

## Practical Application: "Is This Front Side?"

Quick checklist at entry time:

```
1. What is the MACD line on the 1-minute chart?
   > 0 → front side, proceed
   ≤ 0 → back side, SKIP

2. Is the stock making new highs?
   Yes → front side confirms
   No (lower highs) → back side signal, skip

3. What is price relative to VWAP?
   Above VWAP → front side
   Below VWAP and failing to reclaim → back side

4. What is the volume pattern?
   High on green candles, low on red → front side
   High on red candles, low on green → back side

If any answer is "back side" → no trade.
If all answers are "front side" → proceed to pattern detection.
```

---

## jTrader Decision Rules

```
FRONT_SIDE_GATE (corrected implementation):

  # Requires: macd_data['macd_line'] = 12 EMA - 26 EMA

  IF ecfg.enable_macd AND macd_line is not None:
    
    # Skip gate for patterns that don't require it
    IF detected_pattern in ['GAP_AND_GO', 'VWAP_RECLAIM']:
      pass  # These patterns handle their own momentum validation
    
    ELIF macd_line <= 0:
      return None  # Back side — no trade

  # Histogram flip for exits (separate from entry gate):
  # See exit_engine.py enable_macd_flip_exit
```

---

## Data Confidence

| Finding | Confidence | Notes |
|---------|------------|-------|
| MACD line > 0 = front side rule | High | Explicit Ross Cameron rule, consistent across all session summaries |
| Histogram vs line distinction | High | Verified from RC strategy documentation + corpus session narratives |
| Pattern-specific MACD relevance % | High | Computed from RC_STRATEGY_STATISTICS.md 5,010 trades |
| MACD line calculation correctness | Medium | Depends on indicators.py implementation — verify `'macd_line'` key exists |
| Optimal MACD periods (12/26/9) | High | Standard periods used by Ross |
| MACD_STATE corpus field | Low | 391 coded entries (390 = "unknown") — field was not systematically populated; qualitative narrative evidence is primary source |
