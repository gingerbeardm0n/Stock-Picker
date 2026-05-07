# Concept: Time of Day

**Last updated:** 2026-05-07  
**Source:** RC_STRATEGY_STATISTICS.md — 1,787 sessions; concept_pattern_playbook.md  
**Core finding:** 9:30–10:30am = 71.9% win rate (hot market). After 11am = dead zone.

---

## Definition

Time of day is one of the most reliable filters in Ross Cameron's strategy. The strategy is built around the first 60-90 minutes of the trading session — the "morning momentum window." After that window closes, trade quality degrades significantly.

This is not a mechanical rule with a single threshold — it interacts with market temperature, pattern type, and account state. But the directional finding is consistent: **earlier is better.**

---

## Market Temperature × Time

Time of day effects cannot be separated from market temperature:

| Market Condition | Trades | Win Rate | Avg Result | Total P&L |
|---|---|---|---|---|
| hot | 2,437 | **71.9%** | **+$3,516** | +$8,161,473 |
| neutral | 943 | 64.9% | +$813 | +$725,226 |
| cold | 1,556 | 53.9% | **-$63** | -$93,076 |

**Cold markets are net-losing** (-$63/trade avg over 1,556 trades). On cold days, the morning window is compressed or absent — the patterns don't set up cleanly. This is the most critical interaction: time + market temperature together determine whether any trade should be taken.

Sessions per condition:
| Market | Sessions | Avg trades/session |
|---|---|---|
| hot | 651 | 3.8 |
| neutral | 297 | 3.2 |
| cold | 450 | 3.5 |

Cold days have nearly as many trades (3.5 avg) as hot days (3.8) — Ross is trading nearly as often on cold days but getting net-negative results. This is a behavioral finding: on cold days, the correct answer is fewer trades or none, but in practice the trade count barely drops.

**jTrader implication:** Cold market = position size reduction of 50%+ OR halt new entries entirely.

---

## The Morning Momentum Window

Ross describes the primary window as **9:30am–10:30am ET**. Data confirms this.

### Pattern-specific time windows (from playbook)

| Pattern | Primary Window | Notes |
|---|---|---|
| gap-and-go | premarket → 9:30–10:30am | Premarket entries valid; first 15 bars after open are ideal |
| micro-pullback | 9:30–10:30am | Strictly pre-10:30. After 10:30, micro-pullback = macro reversal |
| dip-buy | 9:30–11:00am | 1-hour window; after 11am, dips tend to extend rather than recover |
| vwap-reclaim | 9:30–11:00am | First VWAP test of the day; morning session only |
| halt-resume | any (halt-driven) | Time-agnostic — driven by halt events, but quality decays after 11am |
| whole-dollar-break | 9:30–10:30am | Psychological levels most effective in morning momentum |
| flat-top | premarket or early market | Premarket structure; open = entry trigger |
| red-to-green | 9:30–10:00am | First 30 minutes; R2G moves after 10am are often fades |

**Consensus:** Most patterns have hard or soft cutoffs at 10:30am–11:00am.

---

## The Dead Zone: 11am–2pm

Ross explicitly identifies 11:00am–2:00pm as the "dead zone" — the period between morning momentum and afternoon continuation:

- Volume drops significantly (institutional order flow completes by 11am)
- Spreads widen (market maker activity decreases)
- Patterns that formed in the morning often consolidate or reverse
- VWAP becomes less meaningful as the day's volume curve flattens
- News catalysts from premarket have been fully priced in

**From jTrader:** `time_decay_hour=12` (exit profitable positions after noon). This is slightly late vs Ross's strategy — he often stops trading at 11am, not noon. The `TRADING_END_HOUR = 11` gate is correct for entry; the exit at noon gives extra time for positions already open.

---

## The Afternoon Window: 2pm–Close

Ross occasionally trades the 2:00–4:00pm window but explicitly flags it as lower quality:

- Only on "continuation" setups where morning momentum stocks are resuming
- Requires fresh catalyst (news in the afternoon, halt-resume, sector news)
- Position sizes smaller (half normal)
- Not a systematic setup — opportunistic only

**Data:** `continuation` category = 181 trades, 64.6% win rate, +$2,308 avg. This is the afternoon continuation data. Win rate is decent but trade count is small relative to morning patterns (181 vs 944 for pullback/dip), suggesting Ross is selective about afternoon trades.

---

## Pre-Market: 6am–9:29am

Premarket is part of the strategy — Ross trades it:

- Primary activity: monitoring, building watch list, observing price action
- Entry: gap-and-go setups sometimes entered premarket if breakout is clear (FILE 0308: VWAP reclaim at 7am)
- Risk: wide spreads, low volume, one whale can move the price
- Best premarket entries: VWAP reclaim on clear news catalyst with building volume

**Premarket entry rules:**
1. Volume must be building, not declining
2. Spread must be manageable (≤1% of price)
3. News catalyst must be specific and still fresh
4. Stock must have traded through key levels already (not just gapping in thin air)

---

## Pattern Priority by Time Window

### 9:30–9:45am (Opening 15 minutes)
Best patterns: gap-and-go (premarket high break), opening-range (first candle break)  
Caution: wide spreads, violent price action, large candles  
Position size: reduced (half or quarter) due to uncertainty

### 9:45–10:30am (Prime window)
Best patterns: micro-pullback, dip-buy, whole-dollar-break, flat-top, halt-resume  
Full position size allowed (if market is hot)  
This is the highest-edge window in the entire strategy

### 10:30–11:00am (Late morning)
Best patterns: vwap-reclaim, halt-resume, dip-buy (first dip only)  
Micro-pullback: avoid  
Position size: 50-75% of normal  

### 11:00am–2:00pm (Dead zone)
No new entries unless halt-resume or major news catalyst  
If in position: manage exits aggressively, don't add  
Time-decay exit: close profitable positions that aren't actively moving

### 2:00–4:00pm (Afternoon)
Continuation plays only (stocks making new highs from morning)  
Fresh catalyst required  
Half size maximum

---

## Account State and Time

Behavioral data shows time-of-day effects are amplified by account state:

| Account State | Win Rate | Avg Result | Behavior |
|---|---|---|---|
| in-drawdown | 39.7% | -$2,717 | Trades LONGER into dead zone trying to recover |
| exceeded-goal | 77.8% | +$7,064 | Stops trading EARLY — this win rate reflects morning-only trades |
| building-cushion | 72.1% | +$1,874 | Stops at logical morning exit points |
| normal | 61.6% | +$1,021 | Continues into dead zone more often |

The `exceeded-goal` 77.8% win rate is a time-of-day artifact: Ross stops when he hits his goal, which is typically before 11am. He's implicitly enforcing the morning window via goal-based stopping.

**jTrader implication:** The give-back-half and exceeded-goal halts in `PortfolioManager` are time-of-day enforcement mechanisms in disguise.

---

## Time Decay Exit Implementation

Current jTrader: `time_decay_hour=12` — exits profitable positions at noon.

Ross's stated rule: "After 11am, if I'm profitable, I'm out. Morning momentum is done."

Options:
1. Tighten to `time_decay_hour=11` (strict Ross rule)  
2. Keep `time_decay_hour=12` but add a raise-stop rule at 11am (position still runs but with much tighter stop)  
3. Add position-size reduction at 10:30am (half size if in position, no new entries)

Trial 193 used `time_decay_hour=12` — this is the backtested optimum and should be retained until a backtest shows otherwise.

---

## jTrader Decision Rules

```
TIME_OF_DAY gates:

  TRADING_START = 9:30 ET
  PRIME_WINDOW_END = 10:30 ET
  ENTRY_CUTOFF = 11:00 ET (TRADING_END_HOUR)
  DEAD_ZONE_END = 14:00 ET
  TIME_DECAY_EXIT = 12:00 ET

  At each bar:
  
  # Entry gates
  IF current_time < TRADING_START:
    IF market_hot AND pattern == 'GAP_AND_GO' AND volume_building:
      ALLOW premarket entry (special case only)
    ELSE:
      BLOCK entry

  IF current_time >= ENTRY_CUTOFF:
    BLOCK all new entries → TIME_DECAY

  # Position size modifiers by time
  IF current_time in [TRADING_START, 09:45]:
    position_size_multiplier = 0.5  # opening 15 min: half size
    
  IF current_time in [09:45, PRIME_WINDOW_END]:
    position_size_multiplier = 1.0  # prime window: full size

  IF current_time in [PRIME_WINDOW_END, ENTRY_CUTOFF]:
    position_size_multiplier = 0.75  # late morning: reduced

  # Exit gate
  IF current_time >= TIME_DECAY_EXIT AND position.is_profitable:
    EXIT → TIME_DECAY_EXIT

  # Pattern-specific overrides
  IF pattern == 'HALT_RESUME':
    IGNORE time gates (halt-driven, not time-driven)
    
  IF pattern == 'MICRO_PULLBACK' AND current_time >= PRIME_WINDOW_END:
    BLOCK entry → "MICRO_PULLBACK_TIME_CUTOFF"
```

---

## Data Confidence

| Finding | Sample | Confidence |
|---|---|---|
| Hot/cold market win rates | 2,437 / 1,556 trades | High |
| Cold market net-losing (-$63/trade) | 1,556 trades | High |
| Morning window 9:30–10:30am | Qualitative from recaps | High |
| Dead zone 11am–2pm | Direct Ross statement + qualitative | High |
| Pattern-specific time cutoffs | Qualitative (playbook) | Medium |
| Premarket entry quality | Small sample (subset of gap-and-go) | Low |
| Afternoon continuation win rate | 181 trades (continuation category) | Medium |
