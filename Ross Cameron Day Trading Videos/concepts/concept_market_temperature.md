# concept_market_temperature.md
# jTrader Concept: Market Temperature

**Last Updated**: 2026-05-21
**Source**: Full corpus analysis — TRANSCRIPT_SUMMARIES_0001-1799 (all 1,799 sessions)
**Previous version**: Built from FILES 0001-0199 only — contained fundamental ratio error
**Status**: Active — drives parameter adjustment logic

---

## Overview

Market temperature is Ross Cameron's primary context filter — the first question he answers each morning before sizing or selecting setups. It is not a momentum indicator. It is a classification of how the entire market is behaving that day.

### Corrected Distribution (full 1,799-session corpus)

| Temperature | Sessions | % | Description |
|-------------|----------|---|-------------|
| HOT | ~867 | 46% | Aggressive mode — multiple runners, high conviction |
| COLD | ~657 | 32% | Defensive mode — A+ only, small size, early exit |
| NEUTRAL | ~390 | 19% | Base-hit mode — standard setups, moderate size |
| CHOPPY | ~36 | 2% | Survival mode — minimize exposure, may skip session |

**HOT is the most common state**, not the rarest. The prior version of this document claimed a 1:2.7 hot:cold ratio based on a 200-session sample that happened to cover an unrepresentative cold period early in Ross's career. The full corpus inverts that conclusion.

**Cold is NOT the default.** The correct default is: read the scanner each morning and classify based on what you see. No pre-loaded assumption about the day.

---

## 1. Temperature States Defined

### HOT (46% of sessions)

Ross uses: "hot market", "hot tape", "momentum day", "strong momentum", "market is on fire", "really good day", "everything is working"

**Operational definition**: Multiple stocks moving 30%+ intraday with high relative volume. Gap scanner shows strong pre-market action with 4-8 stocks worth watching. Setups that normally fail are following through.

Characteristics:
- Leading gapper up 50%+ pre-market, ideally with news catalyst
- Multiple stocks hitting high-day-momo scanner before 9:30 AM
- First 5-minute candle makes new high and holds
- Halts are predominantly halt-up (circuit breaker on upside)
- P&L targets exceeded within 30-60 minutes of open
- Ross uses phrases like "this is a stock I've been waiting for"

Examples from data:
- FILE 0003: LUCY up, "hot market", volume high — +$12,553
- FILE 0007: ENSC biotech news, "hot market", volume high — +$26,553
- FILE 0011: DRUG + PEGGY + SOBR running simultaneously — +$40,854
- FILE 0114: HOLO (3000%), SYRA, HKIT all running same day — volume high

**Behavioral risks on HOT days** (highest frequency of deviation in metadata):
- FOMO-entry after missing the initial move
- Oversize after early wins (FILE 0011: gave back $12K on DRUG at highs)
- Revenge-trade after first stop-out in otherwise hot session
- Ross's rule: set a profit stop ("if I give back $2,000 from peak, I close everything")

---

### NEUTRAL (19% of sessions — missing from prior concept page)

Ross uses: "normal day", "decent day", "moderate momentum", "some opportunity", "selective day"

**Operational definition**: Scanner shows 2-4 tradeable stocks, leading gapper up 20-50%, volume is present but not explosive. Setups work when they're clean; marginal setups fail.

Characteristics:
- Leading gapper up 20-50%, may or may not have news
- 2-4 stocks on watchlist (vs 4-8 on HOT, 1-2 on COLD)
- First candles show some follow-through but not explosive
- P&L accumulates in the $2,000-$8,000 range
- Ross trades with full size but does not add aggressively

**NEUTRAL is a real, distinct category** — not just "warm cold." Size behavior confirms it sits between HOT and COLD:
- Full size: 61% of sessions (vs HOT 64%, COLD 50%)
- Reduced size: 29% (vs HOT 17%, COLD 38%)
- Oversized: 9% (vs HOT 16%, COLD 10%)

The lower oversizing rate vs HOT (9% vs 16%) indicates Ross doesn't try to press on neutral days.

---

### COLD (32% of sessions)

Ross uses: "cold market", "slow day", "choppy", "difficult day", "not a lot of opportunity", "grinding small profits", "base hits day", "market attention scattered", "bear market feel", "slow tape"

**Operational definition**: Gap scanner shows weak pre-market action (leading gapper up only 10-20%), few stocks qualify simultaneously, setups that trigger often fail to follow through.

Characteristics:
- Leading gapper up only 10-30% pre-market, often without news
- Scanner shows only 1-2 stocks worth watching
- First candles are choppy — multiple false breakouts
- When Ross enters, stocks frequently flush back to entry
- P&L peak might be $1,000-$3,000
- Session often ends 10:00-10:30 AM with "one trade and done"

Examples:
- FILE 0102: GDC was the only real setup, "cold market" — +$2,071
- FILE 0110: SPRB 130% gap but slow day, volume low — +$1,131 ("short share size kind of day")
- FILE 0116: UNCY only trade, volume low — +$356 ("could have been a no-trade day")

**Cold day success is defined differently.** One trade, $500 green, session ends 10:15 AM = excellent cold day. Goal is not to match HOT day P&L — it is to not give back HOT day gains.

---

### CHOP (2% of sessions — degenerate case of COLD)

A chop day is a subset of COLD where setups trigger but immediately reverse. Multiple entries fail in sequence within the first 30 minutes. Win rate drops below 50% on what look like valid setups. Each entry is stopped out but the move happens after the stop.

**Trigger**: One clear event declares chop. Most common: leading gapper fails immediately at open.
- FILE 0111: TON: -148% gap. "Leading gapper SLNG failed immediately, signaling a choppy day ahead." Ross took 5 trades, 2W-3L, session ended 10:00 AM.

**Chop day response protocol**:
1. Immediately stop adding to any losing position
2. Reduce share size to minimum (25-50% of cold-day size)
3. Wait for one extended-consolidation breakout — do not trade out of frustration
4. Skip second/third entries on any stock that already failed once today
5. Stop condition: 3 consecutive losses → stop for the day regardless of time

**What chop days cost**: The worst outcomes in the dataset are cold/chop days where Ross overrode the chop signal and continued trading.
- FILE 0519: Chop + revenge = -$11,318 (hit max loss, called broker to increase limit)
- FILE 0521: Cold signals ignored, oversized DLPN revenge = -$65,000 (career worst at time)

---

## 2. How to Detect Market Temperature in Real Time

### Key Principle: Same-Day Read, Fresh Every Morning

**Ross does NOT use yesterday's market temperature as a predictive input for today.** Confirmed across 1,799 sessions: he reads the scanner each morning and classifies based on what he sees, regardless of what happened the day before.

What IS multi-day: Ross carries personal P&L psychology from prior sessions. After a big loss, he trades smaller — but this is behavioral discipline (preventing revenge trading), not temperature prediction. The market could be genuinely HOT on the day after a $20K loss; he would still trade full-size if the scanner shows it.

These are two separate systems:
- **Market temperature**: classified same-day from scanner signals
- **Personal state adjustment**: sized down after big losses until confidence rebuilds

Do not conflate them in jTrader logic.

---

### Premarket Indicators (4:00 AM – 9:25 AM)

**Primary: Gap Scanner Quality**

| Condition | Temperature Signal |
|-----------|-------------------|
| Leading gapper up 50%+ with news catalyst | HOT candidate |
| Leading gapper up 30-50%, no catalyst | NEUTRAL-WARM |
| Leading gapper up 20-30%, weak catalyst | NEUTRAL |
| Leading gapper up 10-20%, no catalyst | COLD |
| Gap scanner showing 0-1 tradeable stocks | COLD / no-trade day |

The gap scanner is the #1 signal. Ross explicitly checks it pre-market. Comments like "pathetic gap scan" (FILE 0103 — leading gapper only up 20% at 6:45 AM, described as making him "reluctant to sit down") vs "scanner lit up" on hot days.

**Secondary: Number of Stocks on Watchlist**

Hot days generate 4-8 stocks worth watching. Neutral days: 2-4. Cold days: 1-2. Zero stocks = no-trade day.

**Tertiary: Pre-Market Volume and Price Action**
- Heavy pre-market volume with clean uptrend = hot signal
- Choppy pre-market with thin volume = cold signal
- Stock that gapped 200%+ but already faded 50% from high by 9:00 AM = cold signal (move "already started")

**Sector Heat**
Multiple stocks from same sector gapping = amplified hot signal. Biotech news sparks sympathy plays; Chinese stocks run in sympathy; crypto names move together. Appeared in FILES 0113 (KPRX + SQL), 0114 (Chinese stocks), 0122 (MEDS + GLTO sympathy).

### Snapshot Time: 9:25 AM

The classification should be locked at **9:25 AM** (5 minutes before open), not 9:15 AM. By 9:25 AM, pre-market volume has ramped, final watchlist is clear, and the signal quality is meaningfully better. Ross's morning prep explicitly converges at this point.

---

### Early Tape Signals (9:30 AM – 9:45 AM)

The first 15 minutes confirm or override the pre-market read.

**First Candle Behavior**
- First candle makes new high and holds = hot/strong confirmation
- First candle spikes and immediately reverses = cold/chop warning
- FILE 0111: "leading gapper SLNG failed immediately, signaling a choppy day ahead"

**Volume at Open**
- HOT: opening volume dramatically higher than pre-market averages; scanner fills immediately
- COLD: opening volume thin; spreads wider; Ross explicitly mentions "thick spreads" and "spoof orders" as cold signals (FILE 0005 re: TWG)

**Halt Behavior**
- Halt-up in first 30-100% move = strong hot signal
- Halt-down in first 15 minutes = cold signal; evidence of trapped buyers and weak follow-through

**MACD State on Leading Stock**
- Positive MACD + price above VWAP = hot confirmation
- Negative MACD diverging = cold signal even on seemingly hot stock

---

### Runtime Temperature Updates (Intra-Day)

Temperature is not static. Updates happen throughout the session:

- First trade loss on clean setup → downgrade one level (HOT→NEUTRAL, NEUTRAL→COLD, COLD→CHOP)
- 2 consecutive losses → force to COLD regardless of premarket
- Leading stock halts DOWN in first 30 minutes → force COLD
- MACD negative on leading stock below VWAP before 9:45 → COLD
- Multiple false breakouts on 2+ different stocks by 9:45 → declare CHOP

Temperature can also **upgrade** intra-day (less common but observed):
- Premarket looked cold, but open tape showed explosive volume → upgrade to NEUTRAL/HOT
- Labeled in data as "hot-start-cold-end-cycle" (in reverse) and "hot-beginning-then-cooling"

Temperature only upgrades if the open tape is unambiguously stronger than premarket suggested. Ross does not upgrade on a single green trade.

---

## 3. Seasonal Patterns (Descriptive, Not Predictive)

Ross knows certain periods are historically cold. During slow-month periods (August, summer, holidays), 61% of sessions classify as COLD vs. the 32% baseline.

Ross explicitly acknowledges:
- "August-slowest-month-historically"
- "summer slowdown" — less institutional participation, thinner tape
- "post-Labor-Day-momentum-explosion" — September often marks the restart of hot markets
- "slow week" / "holiday week" — pre/post major holidays are cold by default

**However**: Ross still reads the scanner fresh each morning. Seasonal context shifts his *threshold* for calling a day hot — he requires stronger evidence in August than in January — but he does not pre-classify the entire month and skip it.

**jTrader implication**: Seasonal context can act as a prior probability adjustment to the classification thresholds, not a hard override. Implement as: `hot_gapper_threshold += 10% during August/holiday weeks`.

---

## 4. Hot Market Rules

### Setup Selection
On hot days, Ross expands the setup universe:
- Gap and go (primary): enter on first pullback or first 5-min candle new high
- News-driven momentum: biotech approvals, reverse splits, uplist/IPO
- Sympathy plays: sector moves create secondary opportunities
- Dip trades: all dip trades have higher success rate on hot days
- Ross explicitly takes lower-quality setups on hot days (FILE 0003: BCDA "lower quality but entered because market heating up")

More stocks per session: hot days often have 3-7 individual positions vs 1-3 on cold.

### Position Sizing
- Full standard position or larger
- Aggressive scaling: add on breakouts, add on dips, pyramid into momentum
- Start with smaller anchor, add as move confirms, scale back as it extends
- Ross does NOT go max size at entry — he starts smaller and adds

### Hold Duration
- Longer holds: 30-60 minutes (vs 5-15 on cold)
- Hold through multiple halt-up cycles
- Multiple full re-entry cycles on same stock acceptable

**Key exit signal even on hot days**: MACD negative cross at highs. When MACD goes negative near day's high, exit full position regardless of how hot the day is.

---

## 5. Neutral Market Rules (NEW — not in prior version)

### Setup Selection
- Trade standard A/B setups, not marginal ones
- 2-4 stocks on radar; take the 1-2 cleanest
- Sympathy plays require stronger evidence than on hot days
- No "good enough" entries — pattern must be unambiguous

### Position Sizing
- Full standard position (61% of neutral sessions = full size)
- One planned add if setup confirms; do not add on uncertainty
- No pyramiding into extended moves
- Take profits at T1, decide on T2 based on intra-bar evidence

### Hold Duration
- Standard 15-30 minute holds
- Exit at T1 unless stock shows clear continuation (second breakout level visible)
- Do not hold through halts unless the setup was HOT-quality from the start

---

## 6. Cold Market Rules

### Setup Selection: A+ Only

The most consistent cold-market rule: trade only the single best setup available. Not second-best or third-best.

Ross's language:
- "No compelling setups" → no trade (FILE 0116)
- "Not a market for hero trades, grinding small profits" (FILE 0112)
- "Cold markets, defense over offense" (FILE 0522)
- "Short share size kind of day" (FILE 0110)

A+ criteria on cold days (stricter than normal):
1. Must have news catalyst (not just technical setup alone)
2. Float must be small (sub-5M preferred, sub-1M ideal)
3. Relative volume must be 3x+ (vs 2x acceptable on hot day)
4. Pattern must be clean — no ambiguity on entry level
5. Pre-market trend intact (not already reversed from gap high)

If leading gapper fails criteria 1-3, Ross either skips entirely or takes 1 small scalp and exits immediately.

### Position Sizing
- Reduced share count (explicit across cold-day sessions)
- No scaling — starter position only, no adds
- Maximum 1 add if setup confirms strongly
- Earlier partial profit-taking (sell 50%+ at first target)
- Practical formula: cold day size = hot day size × 0.5 or less

### Exit Timing
- Take profits at T1, do not hold for T2 or T3
- If stock hesitates at resistance for more than 2-3 candles, exit
- Do not hold through halts on cold days — resume price unpredictable
- **10:00-10:30 AM is the hard stop** (vs optional on hot/neutral days)

Ross: "on slow days, morning momentum is gone by 10:30, there's no reason to stay in."

---

## 7. Chop Day Rules

### When to Declare
1. First 1-2 trades fail on valid setups (entries triggered but immediately reversed)
2. Leading stock shows multiple false breakouts in first 15 minutes
3. 2-3 consecutive losses in first 30 minutes

### Chop Response
- Reduce to minimum size (25-50% of cold-day size)
- Skip any pattern that already failed once on that stock today
- Only trade breakouts from extended flat consolidation (not choppy back-and-forth)
- Stop condition: 3 consecutive losses → end session regardless of time

---

## 8. Personal State vs. Market Temperature (Critical Distinction)

These are two separate systems that must NOT be conflated in jTrader:

| Signal | Type | Driver | Response |
|--------|------|---------|----------|
| Market temperature | Same-day scanner read | Gap quality, watchlist count, first candle | Adjust position size, setup filter, session stop |
| Personal state | Multi-day P&L streak | Consecutive losses, big single loss | Reduce size until psychology stable |

After 3-4 consecutive red days, Ross reduces size. This is a **behavioral guardrail** — he is likely revenge-trading, oversizing, forcing setups. The market may be genuinely HOT on day 4; he still trades smaller because he knows his own emotional state is compromised.

**Do not build "3 red days → cold market classification" into jTrader.** The market does not care about Ross's P&L streak. Classify temperature from scanner signals only. Apply personal-state size adjustments as a separate multiplier if needed.

---

## 9. jTrader Implementation

### Temperature Detection

**Snapshot at 9:25 AM ET** (improved from prior 9:15 AM):
```python
temperature_premarket = classify_premarket(
    leading_gapper_pct,          # gap % of best scanner stock
    qualifying_symbols_count,    # stocks passing FULL 5-pillar scan (not loose pre-filter)
    has_news_catalyst,           # from news API (not yet available in backtest)
    premarket_volume_ratio,      # today vs historical avg at this time
    sector_sympathy_count        # stocks in same sector gapping
)
```

Classification thresholds (from data, subject to Optuna tuning):
- `gapper >= 50%` AND `symbols >= 4` → HOT
- `gapper >= 30%` OR `symbols >= 3` → NEUTRAL
- `gapper >= 15%` AND `symbols >= 2` → NEUTRAL (weak)
- `gapper < 15%` OR `symbols <= 1` → COLD
- Leading gapper fails at open → upgrade to CHOP warning

### Parameter Adjustments by Temperature

| Parameter | HOT | NEUTRAL | COLD | CHOP |
|-----------|-----|---------|------|------|
| max_position_pct | 20% | 15% | 10% | 5% |
| setup_quality_min | 3/5 | 4/5 | 5/5 (A+) | 5/5 + news |
| add_on_allowed | yes (2 max) | yes (1) | no | no |
| hold_to_T2 | yes | situational | no (exit at T1) | no (exit early) |
| hold_through_halt | yes | caution | no | no |
| max_trades_per_day | 10+ | 5 | 3 | 1 |
| session_stop_time | 12:00+ | 11:00 | 10:30 | 10:00 |
| daily_loss_limit_pct | 3% | 2% | 1.5% | 1% |
| consecutive_loss_stop | 4 | 3 | 2 | 1 |

### Runtime Updates
```python
# After each trade closes:
state = update_from_trade_result(state, win=trade.pnl > 0)
# Consecutive losses trigger downgrade: HOT→NEUTRAL, NEUTRAL→COLD, COLD→CHOP
```

### Seasonal Prior (optional, future)
During known slow periods, shift classification thresholds:
- August: `hot_gapper_threshold += 10%`, `hot_symbols_min += 1`
- Holiday weeks: treat as COLD unless strong evidence of HOT

---

## Key Takeaways for jTrader

1. **HOT is the most common state (46%).** Run in HOT mode most of the time. COLD is the exception (32%), not the rule. Reverse of prior documentation.

2. **NEUTRAL (19%) needs its own logic.** It is not cold with slightly bigger size. It is a genuine middle regime with its own setup filter, sizing, and hold behavior.

3. **Temperature is same-day from scanner.** No multi-day carryover. Read fresh each morning.

4. **Personal state and market temperature are separate.** A big loss yesterday makes Ross trade smaller — that is psychology management, not temperature classification. Do not conflate.

5. **The first failed setup is a temperature signal.** A clean setup that fails immediately = evidence tape is cold. Do not retry. Reduce size and wait.

6. **Chop days produce the biggest losses.** NOT because Ross traded larger — because he didn't stop when chop conditions appeared. jTrader must hard-stop at `consecutive_loss_stop`.

7. **Seasonal context shifts thresholds, not the entire classification.** August/summer = raise the bar for HOT, but still read the scanner every day.
