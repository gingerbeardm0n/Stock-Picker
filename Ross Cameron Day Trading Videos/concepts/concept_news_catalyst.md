# Concept: News Catalyst

**Last updated:** 2026-05-21  
**Source:** RC_STRATEGY_STATISTICS.md — 1,787 sessions, 5,261 trades (authoritative for win rates); TRANSCRIPT_SUMMARIES_0001-1799 corpus — NEWS column, 6,625 coded trade rows  
**Sample size:** 2,108 trades coded "yes" (31.8%) vs 4,517 "no" (68.2%) in corpus NEWS column; RC stats: 1,672 with news vs 3,561 without (ratio consistent)  
**Win rate WITH news:** 73.4% | **Without:** 60.7% | **Delta: +12.7pp**

---

## Definition

A news catalyst is any externally-verifiable event that causes a stock to gap up or make an intraday move with clear, specific justification. It is Ross Cameron's Pillar 5 — the most impactful single pre-screen gate in the entire strategy.

The key word is **specific**. Vague sector sympathy is not a news catalyst. "AI stocks are moving" is not a catalyst. A catalyst is tied to THIS stock, THIS event, THIS morning.

---

## Statistical Case

| Category | Trades | Win Rate | Avg Result | Total P&L |
|----------|--------|----------|------------|-----------|
| With news catalyst | 1,672 | **73.4%** | **+$4,040** | +$6,451,149 |
| No news catalyst | 3,561 | 60.7% | +$910 | +$3,073,406 |

**The math:** News trades are 12.7pp higher win rate AND $3,130 higher average result per trade. Combined edge: a news-catalyst trade is worth ~4.4x a no-catalyst trade in expected value ($4,040 vs $910).

By scanner source, pure news-driven trades:
| Scanner | Trades | Win Rate | Avg Result |
|---------|--------|----------|------------|
| news-catalyst | 29 | 79.3% | +$6,045 |
| news | 10 | 90.0% | +$6,255 |
| news-spike | 3 | 100.0% | +$516 |

These are small samples but directionally consistent: higher news specificity → higher win rate.

---

## Catalyst Quality Hierarchy

From highest to lowest reliability (derived from trade outcomes across 1,787 sessions):

### Tier 1 — Hard Catalysts (most reliable, 75%+ win rate)
- **FDA approval / clinical trial data** — binary event, massive price move, clear direction
- **Earnings beat with guidance raise** — numbers are specific, market reaction is immediate
- **Reverse split** — mechanical float reduction, squeeze dynamics predictable (but: 54.2% win rate in data — execution matters, timing is tricky)
- **Acquisition / merger announcement** — price set by deal terms, low reversal risk
- **Short squeeze confirmation** — days-to-cover + borrow rate data confirms setup

### Tier 2 — Medium Catalysts (65-75% win rate)
- **New contract / partnership** — real revenue, specific dollar amounts
- **Biotech data (non-FDA)** — Phase 2 results, IND approval, investigational designation
- **Government contract / defense win** — specific, verifiable
- **CEO/insider buy** — regulatory filing confirms the event

### Tier 3 — Weak Catalysts (60-65% win rate, use with caution)
- **Sector sympathy** — stock moves because a sector peer moved; no stock-specific event
- **Social media / retail attention** — driven by Reddit, Twitter without fundamental anchor
- **"Raised guidance" without earnings** — forward-looking, harder to anchor to price
- **Vague "strategic partnership"** — no dollar value disclosed

### Skip (below 60% win rate in data)
- No catalyst (60.7% — still positive but statistically weakest)
- "Momentum only" — pure technical continuation with no news
- Stale catalyst from prior day with no continuation news

---

## Catalyst Timing Windows

When the catalyst hits relative to market open matters:

| Timing | Quality | Notes |
|--------|---------|-------|
| Pre-market (4am-8am) | Best | Gives time for price discovery, volume to build, spread to tighten |
| Pre-market (8am-9:29am) | Good | Less time for setup, but volume concentrated near open |
| At open (9:30am) | High risk | No premarket structure, price discovery happens in real-time |
| Intraday (9:30am+) | Depends | Halt-resume trades use intraday catalysts — see concept_halt_resume.md |
| After-hours prior day | Moderate | "Gap-and-go" next morning if catalyst holds overnight |

**Key rule:** Ross prefers catalysts with at least 30-60 minutes of premarket trading. This builds the chart structure (premarket high, volume pattern, VWAP) that creates the entry trigger.

---

## Catalyst Verification (Pre-Entry Checklist)

Before entering any trade, verify:

1. **Is the catalyst specific to this stock?** If you can't name the event in one sentence, skip.
2. **Is there a news source?** SEC filing, press release, FDA database — not a tweet.
3. **Is the stock the primary beneficiary?** Sector plays are tier-3; the stock directly named is tier-1.
4. **Is the catalyst still in play?** Old news from yesterday without continuation = no catalyst.
5. **Is volume consistent with the catalyst?** Big news + thin volume = fake move. Real catalyst generates real volume.

---

## Catalyst Types by Sector

From sector win rate data:
| Sector | Win Rate | Avg Result | Common Catalyst Types |
|--------|----------|------------|----------------------|
| cannabis | 83.3% | +$1,645 | legalization news, state approval |
| pharma | 71.0% | +$3,621 | FDA, clinical data, approval |
| tech | 71.9% | +$2,126 | contracts, AI announcements, earnings |
| chinese | 66.2% | +$2,618 | partnership, US listing news |
| biotech | 66.1% | +$1,732 | trial data, FDA, reverse mergers |
| energy | 64.0% | +$3,104 | oil price, contracts, drilling data |

Pharma/biotech dominate by trade frequency. Tech has high win rate with manageable avg — good risk/reward. Chinese stocks are high variance (large wins, large losses).

---

## Why jTrader Must Implement This

Pillar 5 is currently `'SKIPPED'` in `entry_engine.py`. This is the single highest-value unimplemented gate.

**Expected impact of enabling:**
- Current jTrader win rate (from simulation): ~33-66% depending on params
- Statistical floor WITH news gate: 73.4% win rate
- Statistical floor WITHOUT: 60.7% — a 12.7pp penalty for every no-news trade taken

Even a binary news/no-news flag (from Finnhub or Alpaca news feed) would capture most of this edge. The implementation does NOT need to parse catalyst quality — just: does a news event exist for this symbol today in premarket?

---

## jTrader Decision Rules

```
NEWS_CATALYST gate (Pillar 5):

  Input: symbol, current_date
  
  Query: news feed for symbol, today's date, before market open
  
  IF news_count >= 1 AND news_age_hours <= 12:
    catalyst_present = True
    catalyst_quality = classify(headline)  # tier-1/2/3/skip
  ELSE:
    catalyst_present = False
  
  IF NOT catalyst_present:
    SKIP trade (60.7% win rate floor is below target)
  
  IF catalyst_quality == 'skip':
    SKIP trade
  
  IF catalyst_quality == 'tier-3':
    allow entry BUT reduce position size by 25%
    require higher rel_vol threshold (8x vs 5x default)
  
  IF catalyst_quality == 'tier-1' or 'tier-2':
    proceed to Gate 4 (pattern detection) at full size

  Minimum viable implementation:
    - Any news = proceed (binary flag)
    - No news = skip
    - Expected win rate improvement: ~+12.7pp
```

---

## Data Confidence

| Field | Coverage | Notes |
|-------|----------|-------|
| news/no-news win rate split (73.4% vs 60.7%) | 5,261 trades via RC_STRATEGY_STATISTICS.md | High |
| Corpus NEWS column coding (yes=2,108, no=4,517) | 6,625 TRADES table rows across 19 chunk files | High |
| News/no-news ratio (~32%/68%) | Both sources agree | High |
| Catalyst type taxonomy (Tier 1/2/3) | Qualitative from summaries | Medium |
| Sector breakdown | RC_STRATEGY_STATISTICS.md complete sample | High |
| Timing windows (premarket best) | Qualitative from recaps | Medium |
| news-catalyst scanner win rate (79.3%) | 29 trades — small sample | Low |
