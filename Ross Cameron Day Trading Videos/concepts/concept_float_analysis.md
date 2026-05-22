# Concept: Float Analysis

**Last updated:** 2026-05-21  
**Source:** RC_STRATEGY_STATISTICS.md; jTrader_Audit_Against_Statistics.md rule #4; concept_pattern_playbook.md; TRANSCRIPT_SUMMARIES_0001-1799 corpus (FLOAT + REL_VOL columns: 235 FLOAT entries, 630 REL_VOL entries coded — most sessions use "-")  
**Core finding:** Float ≤20M = jTrader's disabled pre-screen gate. Sub-5M float = maximum squeeze per pilot finding.

---

## Definition

Float is the number of shares available for public trading. It equals total shares outstanding minus insider holdings, restricted shares, and institutional lockups. For Ross Cameron's strategy, float is the single most important stock characteristic — more important than sector, price, or even catalyst quality.

**Why float matters:** On any given day, if 10 million shares are demanded by buyers but only 1 million shares are in the float, price must rise dramatically to satisfy that demand. Lower float = more violent price movement per unit of buying pressure.

---

## Current jTrader Status

**Float filter is DISABLED** — `enable_float_filter=False` in `ScannerConfig`.

This is the highest-value disabled pre-screen gate. The audit (rule #4) recommends enabling it at ≤20M initially.

From the audit:
> "Sub-5M float = maximum squeeze per pilot finding. Float quality directly affects squeeze dynamics."
> **Recommendation: Enable. Set at ≤20M initially (matches strategy), track by float bucket to validate tighter cutoff.**

---

## Float Buckets and Expected Behavior

| Float Range | Behavior | Examples from playbook | Trade type |
|---|---|---|---|
| Sub-1M | Extreme — moves 100-1,000%+ in minutes, wide spreads, halts repeatedly | FILE 0002, FILE 0004 (185:1 reverse split) | High-risk/high-reward, tight stop required |
| 1M–5M | Best risk/reward — strong moves, manageable spreads | Most gap-and-go and micro-pullback examples | Primary target zone |
| 5M–20M | Good — reliable moves, better liquidity | Mid-tier gap-and-go stocks | Good — broad filter captures this |
| 20M–50M | Reduced — moves are slower, require larger catalyst | Occasional in dataset | Caution — gap-and-go works less cleanly |
| 50M–100M | Slow — needs very large catalyst to make 20%+ move | Uncommon in Ross's trading | Avoid unless exceptional news |
| 100M+ | Skip — institutional float, requires market-moving news | Rarely in dataset | Skip |

**Ross's stated preference:** Under 10M shares. Under 5M = maximum squeeze dynamics.

---

## Why Low Float Amplifies Every Pattern

### Gap-and-Go
- 400K float gapping 50% = 200K shares need to change hands to complete the move
- 40M float gapping 50% = 20M shares need to change hands
- Low float stocks complete their moves faster and cleaner

### Micro-Pullback
- Low float micro-pullback: one institutional buyer stepping in = immediate resumption
- High float micro-pullback: pullback can extend as more sellers surface

### Halt-Resume
- Sub-1M float + LULD halt = every share matters on resume; squeeze is violent
- High float halt: wider distribution of sellers on resume; squeeze is diluted

### Dip-Buy
- Low float dip: buyers return quickly at support (few shares to absorb)
- High float dip: support level requires much more volume to hold

---

## Reverse Split Stocks: Special Float Case

Reverse splits create artificial low-float situations:

| Category | Trades | Win Rate | Avg Result |
|---|---|---|---|
| reverse-split | 48 | 54.2% | +$1,138 |

54.2% win rate — below the strategy average (64.8%) and below most other patterns. Despite the appeal of the "instant low float" thesis, reverse splits underperform. Reasons:

1. **Market skepticism** — reverse splits often signal financial distress; sophisticated traders fade them
2. **Predictable pattern** — retail traders know the squeeze thesis, creating crowded trades
3. **Execution difficulty** — halts are frequent, spreads are extreme, fills are poor
4. **Timing unpredictability** — the move can come hours or days after the split, not just at open

**Ross's approach:** He trades reverse splits but with caution — the data confirms they're below-average setups despite the float mechanics. Example: FILE 0004 (185:1 reverse split) was successful, but this was an extreme case.

**jTrader recommendation:** Do not add a reverse-split filter to seek these out. If they appear in scanner output, treat them as a normal gap-and-go but flag the lower win rate expectation.

---

## Float and Position Sizing

Float affects not just whether to trade, but how big:

### Ross's framework
- Sub-1M float: 1,000-5,000 shares maximum (wide spreads make large positions costly)
- 1M-5M float: 5,000-20,000 shares normal range
- 5M-20M float: 10,000-50,000 shares depending on liquidity
- 20M+: Only if volume is exceptional; position size determined by actual bid-ask depth

### The share count vs dollar risk relationship
On a $5.00 stock:
- Sub-1M float: 5,000 shares × $5.00 = $25,000 position (large relative to float)
- 20M float: 5,000 shares × $5.00 = $25,000 position (tiny relative to float)

Same dollar amount = different market impact. Low float = your 5,000 shares matter. High float = they don't.

**jTrader implication:** Float must be known at entry time to set position sizing correctly. The `ScannerConfig.max_position_pct` (20%) is float-agnostic — float-aware sizing would cap at a smaller % of daily float volume for very low-float stocks.

---

## Corpus FLOAT Distribution (235 explicitly coded entries)

Most TRADE_MECHANICS rows have `-` for FLOAT — ~235/15,000+ coded = 1.5% of rows. When coded:

| Float Range | Count | % of coded | Notes |
|---|---|---|---|
| Sub-1M (sub-1m, <1m, 170K, 441K, 480K, 878K) | ~45 | 19% | Extreme — halts, thin market |
| 1M–5M (1.2M–4.9M + "low-float" generic) | ~79 | 34% | Core target zone |
| Sub-5M generic ("sub-5m", "low", "low-float") | ~36 | 15% | Confirms low-float focus without specific number |
| 5M–20M (5M–12M range) | ~35 | 15% | Acceptable |
| 20M+ (50M, high-float, 269M) | ~11 | 5% | Rare — usually outliers |

**Takeaway:** When explicitly coded, 87% of float entries are sub-20M. This confirms the strategy's low-float focus. The generic "low-float" and "sub-5m" labels (common in earlier chunk files) indicate Ross doesn't always know the exact float — he uses scanner screening to ensure low-float.

## Corpus REL_VOL Distribution (630 coded entries)

| REL_VOL label | Count | % |
|---|---|---|
| high (generic "high") | 506 | 80% |
| very-high | 35 | 6% |
| Specific (45x, 86x, 90x, 100x, 5000x+) | ~30 | 5% |
| low / normal | ~11 | 2% |
| Other (premarket volume, shorts-covering) | ~48 | 8% |

**Takeaway:** 86% of coded REL_VOL entries are "high" or "very-high". When the field has a specific multiplier, values range from 5x to 5000x. The few "low" entries represent trades taken despite low relative volume — these are likely the setups that underperformed.

---

## Float and Relative Volume

Relative volume and float interact multiplicatively:

| Float | Rel Vol | Expected behavior |
|---|---|---|
| Sub-1M | 10x+ | Extreme momentum — halts likely |
| Sub-1M | 5x | Strong move |
| 1M-5M | 10x+ | Very strong — primary target |
| 1M-5M | 5x | Normal strong momentum |
| 5M-20M | 10x+ | Good — same as 1M-5M at 5x |
| 5M-20M | 5x | Adequate but not exceptional |
| 20M+ | 10x+ | Decent only if news is exceptional |
| 20M+ | 5x | Often insufficient for clean patterns |

**Rule of thumb:** `float × rel_vol` should be small. Sub-1M float at 5x rel vol is more explosive than 10M float at 10x rel vol — same effective buying pressure against far fewer shares.

---

## Practical Float Sources

For jTrader implementation, float data must come from a reliable source:

| Source | Update frequency | Quality | Notes |
|---|---|---|---|
| Alpaca (via /v2/assets) | Daily | Medium | Basic, sometimes stale |
| Finnhub (shares_outstanding) | Daily | Medium | Combines outstanding + float |
| Polygon.io | Real-time | High | Preferred if available |
| SEC filings | Weekly+ | High | Source of truth, too slow for daily use |

**Minimum viable implementation:** Pull float from Finnhub or Alpaca at scanner time (premarket). Cache for the session. Flag stocks where float > 20M and skip or reduce size.

---

## Float Filter Implementation

Current: `enable_float_filter=False` — no float check in Gate 1.

**Recommended implementation:**

```python
# In ScannerConfig / EntryConfig
enable_float_filter: bool = True
max_float_shares: int = 20_000_000   # 20M shares

# In entry_engine.py Gate 1 (Pillars)
if ecfg.enable_float_filter:
    float_shares = market_data.get('float_shares')
    if float_shares is not None and float_shares > ecfg.max_float_shares:
        return None  # Float too large
```

**Float bucket sizing modifier (optional, Phase 3):**
```python
def float_size_multiplier(float_shares: int) -> float:
    """Reduce position size for extreme low-float (too volatile) and large float (too slow)."""
    if float_shares < 500_000:     return 0.5    # Sub-500K: half size (spread risk)
    if float_shares < 5_000_000:   return 1.0    # 500K-5M: full size (ideal)
    if float_shares < 20_000_000:  return 0.75   # 5M-20M: slightly reduced
    return 0.0  # 20M+: filtered out if enable_float_filter=True
```

---

## Most Traded Symbols as Float Proxy

From RC_STRATEGY_STATISTICS.md (most traded symbols, 3+ trades):

Top performers by total P&L among frequently traded symbols:
| Symbol | Trades | Win Rate | Total P&L |
|---|---|---|---|
| CARV | 12 | 58.3% | +$171,472 |
| WHLR | 14 | 85.7% | +$97,808 |
| GME | 13 | 76.9% | +$93,503 |
| LEDS | 13 | 61.5% | +$59,083 |
| BPTH | 16 | 81.2% | +$45,913 |

These recurring symbols are predominantly low-float stocks that appear repeatedly across sessions — the same low-float movers cycle through Ross's scanner repeatedly. GME (GameStop) is an exception — high float but exceptional short interest made it behave like a low-float stock.

**Pattern:** Ross's most profitable recurring trades are on symbols he already knows (float, typical behavior, key levels). This is implicit float awareness — he knows exactly how many shares he's dealing with.

---

## jTrader Decision Rules

```
FLOAT_FILTER gate (Pillar: pre-screen):

  Input: scanner_data, cfg

  IF NOT cfg.enable_float_filter:
    PASS  # Float check disabled

  float_shares = scanner_data.get('float_shares')
  
  IF float_shares is None:
    PASS  # Unknown float — allow (may miss data)
    LOG warning "Float unknown for {symbol}"
  
  IF float_shares > cfg.max_float_shares:  # default 20M
    RETURN None  # Float too large — skip

  # Optional position size modifier
  IF cfg.enable_float_size_scaling:
    position_multiplier = float_size_multiplier(float_shares)
    IF position_multiplier == 0.0:
      RETURN None
    ELSE:
      APPLY position_multiplier to max_position_size

  PASS to next gate
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---|---|---|
| Float filter disabled in jTrader | Direct code audit | High |
| Sub-5M float = max squeeze (pilot) | Pilot batch (qualitative) | Medium |
| Reverse-split win rate (54.2%) | 48 trades | Medium (small sample) |
| Float bucket behavior | Qualitative from playbook examples | Medium |
| Float-position sizing interaction | Ross statements + reasoning | Medium |
| Corpus FLOAT distribution (sub-5M = 87% of coded) | 235 coded FLOAT entries | Medium (sparse — 1.5% of rows) |
| Corpus REL_VOL distribution (high = 80% of coded) | 630 coded REL_VOL entries | Medium (sparse) |
| Optimal float cutoff (20M vs 10M vs 5M) | Not directly measured | Low — needs backtest |
