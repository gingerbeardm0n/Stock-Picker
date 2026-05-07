# concept_position_sizing.md

**Last updated**: 2026-05-06
**Source**: Pass 1 enrichment FILES 0001–1799 + summary qualitative analysis
**Coverage**: 1,006 of ~1,800 FILE entries (56%) mention position sizing

---

## Overview

Position sizing is the single most consequential variable in Ross Cameron's trading system. It determines whether a correct directional call produces a base-hit or a home run, and whether a wrong call produces a manageable lesson or a catastrophic loss. 56% of all session summaries reference sizing explicitly — more than any other mechanical topic.

Ross does not use fixed-share, fixed-dollar, or fixed-percent-of-account sizing as a static rule. He uses a **context-sensitive, cushion-anchored, add-on-the-winner framework** where initial size is deliberately small and position is grown only after the trade proves itself.

---

## 1. Sizing Philosophy

### Risk-based vs. Percent-of-Account

Ross does not quote a single formula. His sizing is guided by two simultaneous constraints:

1. **Stop distance governs initial risk**: He mentally defines a stop before entry (e.g., below the most recent micro-pullback low, below VWAP, below the prior candle's close). The stop distance combined with share count sets the dollar risk for the entry.
2. **Account state governs how much risk is acceptable**: When the account is "in the hole" or the day's cushion is zero, initial size is reduced — sometimes drastically. When the day has already generated a meaningful cushion, size can expand.

The practical formula is implicitly:
```
max_initial_risk = f(daily_cushion, market_temperature, pattern_quality)
shares = max_initial_risk / stop_distance_per_share
```

He never quotes a fixed "risk 1% of account per trade" rule. He thinks in terms of how much he can afford to lose on this specific entry given the current session context.

### Base-Hit Mentality

From FILE 0001 (the million-dollar challenge retrospective): 9,000-share average position, 67% win rate, $1.8K average daily profit across 553 days. The emphasis is consistent green days over maximum daily extraction. Ross explicitly frames losing as "giving back the cushion" and winning as "building the cushion."

---

## 2. Account Stage Scaling

Ross's position sizing evolved as his account grew. The data across ~1,800 sessions shows three distinct operational stages:

### Stage 1 — Small Account ($583 → ~$10K)
- **Share counts**: 1,000–3,000 shares standard; 5,000 maximum
- **Price range focus**: $1–$5 stocks (maximum move per share without wide spreads)
- **Daily goal**: $500–$1,000
- **Max loss per day**: ~$500–$1,000 (would wipe meaningful % of account)
- **Behavior**: Extreme selectivity, trade only the best setup of the day. Stops are tight because account cannot absorb large losses.

### Stage 2 — Growth Account ($10K → ~$100K)
- **Share counts**: 3,000–9,000 shares standard
- **Daily goal**: $2,000–$5,000
- **Max loss per day**: $3,000–$5,000
- **Behavior**: Scaling-in becomes viable. First trade is still a starter (1,000–2,500 shares); adds are made on confirmation. From FILE 1406: "start with 5,000-share maximum, promise not to increase to 10,000 shares until $1,000 profit."

### Stage 3 — Large Account ($100K+)
- **Share counts**: 9,000–20,000 shares on normal setups; 40,000–50,000 shares on exceptional setups with strong cushion
- **Daily goal**: $5,000–$10,000 (noted as $10.8K daily average in 2017 year review, FILE 0009)
- **Max loss per day**: $5,000–$10,000 (explicitly mentioned in multiple sessions)
- **Behavior**: Position size relative to account balance drops — a 9,000-share position at $5/stock is $45K, which is a smaller fraction of a $500K account than it was of a $50K account. Hot streaks allow temporary size expansion.

### Key Account-Stage Insight
FILE 0001 documents the challenge structure: Ross kept maximum account balance at $50–75K at any time by taking monthly withdrawals. This is structural risk management — not letting the account grow so large that position sizing becomes psychologically distorted. The challenge itself ran on a sub-$100K account even while generating $1M+ cumulative.

---

## 3. Float-Adjusted Sizing

Float is the primary filter for position size, not just stock selection.

### Sub-1M Float
- **Characteristics**: Thin market, fast moves, wide spreads as momentum builds
- **Sizing rule**: Start smaller than usual. Example from FILE 0004 (WETG, sub-1M float): started 2,000 shares, added 2,000, 2,000, 1,500. Explicitly reduced position as price extended because "spreads widen and volatility elevated."
- **Add logic**: Add on confirmation of each new level break, not anticipating it.
- **Exit rule**: Reduce size into parabolic conditions — front-load early, de-risk as patterns weaken.

### Low Float (1M–5M shares)
- **Standard operating territory** for the strategy
- **Share counts**: 5,000–12,000 shares on normal setups
- **Add logic**: Build through micro-pullback levels. FILE 0007 (ENSC): started 2,900 shares at $2.90, added at $3.50 break, $4.00 break, $4.50 dip, maxed at 4,500 shares — a relatively conservative peak because the price was already extended.
- **Float confirmation required**: Ross verifies float before committing full size. "Sub-1M float confirmed" is a prerequisite for high-conviction entries (FILE 0002).

### Mid Float (5M–20M shares)
- **Reduced relative size vs. low float**
- Position sizes are similar in share count but the expected move per share is smaller, so P&L potential per trade is lower. Ross often reduces enthusiasm and moves on faster.
- High-float stocks can work (FILE 0011, DRUG with high float: 4,000 shares maximum), but the sizing ceiling is lower and exits are faster.

### Float Size → Maximum Shares (rough guidelines from observed trades)
| Float Range | Typical Max Shares | Rationale |
|---|---|---|
| Sub-1M | 2,000–5,000 | Thin market, slippage risk |
| 1M–3M | 5,000–15,000 | Core zone, best liquidity for size |
| 3M–10M | 3,000–9,000 | Still workable but smaller edge |
| 10M+ | 1,000–5,000 | Larger float = smaller % moves = smaller edge |

---

## 4. Scaling-In Mechanics

Scaling in is Ross's dominant execution pattern. From the 5,010-trade dataset: scaling-related add-on mechanics appear in 274 out of 5,010 recorded trades (scaling: 113, added on move: 108, scaled entry: 34, added on dips: 19).

### When Ross Adds to a Position

**Condition 1 — After a cushion is established from the initial entry**
The first lot must be profitable (or at minimum at breakeven) before adding. FILE 1406: explicit rule — maximum 5,000 shares until $1,000 profit, then authorized to go to 10,000 shares.

**Condition 2 — On the break of a new level**
Adds happen at whole-dollar and half-dollar breaks, or on the break of a prior day's high. Not into resistance — on the break through it.

**Condition 3 — On micro-pullback dips**
After a move up, Ross buys the first clean dip (the "micro-pullback") if MACD is still positive and the dip is shallow. This is the most common add mechanic.

**Condition 4 — At halt resumes when direction is confirmed**
Circuit breaker halts provide a forced pause. On resume, if the stock immediately goes higher, Ross adds. If the resume shows weakness, he reduces or exits.

### Scaling-In Sequences (observed from trade tables)

From FILE 0003 (LUCY): 2,500 → 5,000 → 7,500 → 10,000 → 12,500 → 15,000 → 17,500 shares. This is an extreme case (exceptional catalyst, MACD positive throughout, fresh news).

From FILE 0004 (WETG): 2,000 → 2,000 → 2,000 → 1,500 → 4,500 → 1,500 → 1,000. Note the final entries are progressively smaller as the stock extended — a deliberate de-escalation.

From FILE 0009 (ZZZZ): 1,800 initial → adds at $9.21, $9.25, $9.46, $9.70, $9.88 → total 45,000 shares. Largest observed position in the dataset. This was a pyramid on an extraordinary momentum day.

Normal scaling sequence (most common pattern):
```
Entry: starter position (25–33% of intended max)
Add 1: on break of first resistance level (bring to 50–66% of max)
Add 2: on micro-pullback dip if still in momentum (bring to 100% of max)
[If extended move]: reduce position size, never add at all-time high of day
```

### What Ross Does Not Do
- Does not add to a losing position (averaging down). Any mention of this in the data is flagged as a behavioral deviation.
- Does not add after a stock has made a parabolic move without a proper pullback.
- Does not add in the last 30 minutes before hitting stop territory — this is explicitly called out as a discipline failure in multiple sessions.

---

## 5. Scaling-Out Mechanics

From the 5,010-trade dataset: scaled exits (50 instances) and scaled at resistance (23 instances) are the dominant exit patterns. Single-exit close-entire-position trades are the minority.

### Standard Partial Exit Sequence

**T1 (first target) — sell 25–50% of position**
Typically at the next whole-dollar or half-dollar level. Locks in enough to guarantee the trade is a net winner even if stopped on the rest.

**T2 — sell another 25–33%**
At the next resistance level or extended move. This is often described as "letting a runner run" while having already protected profit.

**Remainder — trail or exit on signal**
Held until MACD turns negative, selling volume exceeds buying by 2x, spreads widen, or a pre-defined signal fires. FILE 0002: "stopped momentum trading when MACD turned negative and sellers stacked heavily with 25–30k share blocks."

### Scaling-Out at Halts
Before a halt-up: Ross sells a portion into the momentum surge that triggers the circuit breaker. He does not hold full size through the halt because halt resumes can gap violently in either direction.

After a halt resume: if the stock immediately makes new highs, he may re-add. If it fades, he exits the remainder.

### Quick Scalp Mode
When market temperature is cold or after a prior loss, Ross shrinks to "quick scalp" mode: take 10–15 cents of profit on the initial lot and exit completely. No partials, no trailing. This is explicitly labeled in sessions as a risk-reduction adaptation.

---

## 6. Market Temperature Adjustment

Market temperature (hot / neutral / cold) is the primary overlay that scales all position sizes up or down.

### Hot Market Day
Defined by: leading gapper up 50%+ pre-market, multiple stocks gapping up 20%+ simultaneously, high relative volume across the board, recent successful momentum trades.

- **Size multiplier**: Full size or above. On exceptional days, Ross explicitly authorizes going above his normal ceiling.
- **Daily goal**: Can be extended (e.g., "the market is giving me more — I'll stay longer")
- **Entry style**: More aggressive, smaller starter position as % of intended max (because you expect to be able to add significantly)
- **Example**: FILE 0011 — $40,854 day, traded DRUG through multiple halt-up cycles with 4,000+ share positions

### Neutral Market Day
The default. Most days fall here.

- **Size**: Standard position sizes per the account stage guidelines above
- **Daily goal**: $2,000–$5,000 depending on stage
- **Entry style**: Wait for confirmation before adding. Starter is 33–50% of intended max.

### Cold Market Day
Defined by: leading gapper up less than 20%, no news catalysts, low relative volume, prior red day(s).

- **Size multiplier**: Half-size or less. FILE 1406 explicitly states: "start with 5,000-share max" on a day when normal max is 10,000.
- **Daily goal**: Reduced — $1,000–$2,000. Just stay green.
- **Entry style**: Quick scalp mentality. Take the first 10–15 cents and exit. Do not try to hold for a larger move.
- **Trading window**: Often ends earlier (before 10:00 AM) because quality degrades faster.
- **No-trade days are valid**: FILE 1403 explicitly documents two consecutive no-trade days as disciplined patience.

### Two-Day Rule (Post-Loss Sizing)
After a red day, Ross explicitly reduces size on the following day until a cushion is built:
- FILE 0008: "deliberately slow down, reduce share size, prioritize staying centered"
- FILE 1404: after -$10,000 day on QRX, committed to "reduce position size until he recouped half the loss"
- The recovery period is not time-based — it is cushion-based. Once the account rebuilds enough of the loss, full size returns.

---

## 7. Catastrophic Loss Prevention

### Daily Max Loss Circuit Breaker
Ross maintains a hard daily maximum loss limit. The exact number varies by account stage and market context, but the structure is:

- **Floor (small account)**: $500–$1,000
- **Standard (growth account)**: $3,000–$5,000
- **Large account**: $5,000–$10,000+

When this limit is hit, trading stops immediately for the day. No exceptions, no "one more trade to get it back." Sessions in the data where max_loss_hit=true consistently show early session end.

From FILE 0845 summary: "Max-loss threshold enforced early exit." From FILE 0800 series: max_loss_hit=true is consistently correlated with session ends before 10:00 AM.

### Three-Loss Rule (Intraday Circuit Breaker)
Multiple sessions reference a rule: after 3 consecutive losses, stop trading or dramatically reduce size. This prevents the revenge-trading spiral. FILE 0511: "he maintained position sizing discipline and avoided hitting his three-loss rule, which would have ended his trading day."

### Per-Trade Risk Cap
No explicit fixed-dollar figure, but the behavioral ceiling is implied by stop placement. Ross rarely risks more than:
- $500–$1,000 on a cold market starter
- $1,000–$3,000 on a normal full-size entry
- $5,000–$10,000 on an exceptional hot-market high-conviction trade

The QRX disaster (FILE 1404, -$10,000) was a 4,000-share entry in a stock with thin volume and tight spreads that masked liquidity — a situation Ross later identified as a violation of his own rules. He committed to: remove buy hotkey to force slower entries, reduce size until halfway recovered.

### Withdrawal Discipline
From FILE 0001: Ross kept account balance at $50–75K maximum by taking monthly profit withdrawals. This prevents position sizing from becoming untethered from risk tolerance as profits compound. A $500K account will naturally produce larger positions in dollar terms — the withdrawal rule caps the compounding effect.

---

## 8. jTrader Implementation Rules

These are the concrete formulas derived from the observed patterns above.

### Formula: Initial Position Size

```python
def compute_initial_shares(
    account_balance: float,
    daily_cushion: float,          # P&L so far today
    market_temp: str,              # "hot" | "neutral" | "cold"
    float_shares: int,             # stock float in shares
    stop_distance: float,          # distance to stop in $ per share
    prior_day_result: str,         # "win" | "loss" | "big_loss"
) -> int:
    
    # Base risk budget as % of account
    base_risk_pct = {"hot": 0.02, "neutral": 0.015, "cold": 0.008}[market_temp]
    
    # Adjust for prior day result
    if prior_day_result == "big_loss":
        base_risk_pct *= 0.5   # half size after big loss
    elif prior_day_result == "loss":
        base_risk_pct *= 0.75  # reduced size after any loss
    
    # Adjust for daily cushion (can expand when cushion established)
    if daily_cushion > account_balance * 0.01:   # >1% cushion built
        base_risk_pct *= 1.2
    elif daily_cushion < 0:
        base_risk_pct *= 0.5   # in the hole today — protect
    
    # Calculate max risk dollars
    max_risk_dollars = account_balance * base_risk_pct
    
    # Convert to shares via stop distance
    shares_by_risk = int(max_risk_dollars / stop_distance)
    
    # Float cap: never exceed 5% of float on initial entry
    shares_by_float = int(float_shares * 0.05)
    
    # Hard cap by price range (avoid over-concentration)
    # Assume max_position_value = 20% of account balance
    max_position_value = account_balance * 0.20
    # shares_by_account = int(max_position_value / entry_price)  # caller provides
    
    return min(shares_by_risk, shares_by_float)
```

### Rule: When to Add (Scale-In Gate)

All of the following must be true before adding to a position:

1. Current trade is profitable (or at minimum: breakeven from original entry)
2. MACD is positive (confirmed by scanner data)
3. Stock is at or breaking a new level (whole dollar, half dollar, prior high)
4. Spread has not widened materially since entry
5. Still within the primary trading window (before 11:00 AM ET)
6. Daily max loss is not at risk from this add (i.e., adding the full stop distance on the add lot would not breach daily max)

Add size: add lot should be equal to or smaller than the initial entry. Do not pyramid upward in raw share count at extended prices.

### Rule: Scaling-Out Targets

```
T1 = entry_price + (1.0 × stop_distance)     # 1:1 R — sell 25-33%
T2 = entry_price + (2.0 × stop_distance)     # 2:1 R — sell another 25-33%
Remainder: trail via MACD or 2× selling volume threshold
```

At T1: move stop to breakeven on remaining shares.
At T2: move stop to T1 on remaining shares.

### Rule: Market Temperature Size Multiplier

| Market State | Max Position (% of account) | Daily Goal | Stop Trading After |
|---|---|---|---|
| Hot | 25% | 2× daily target | 2× daily target reached |
| Neutral | 15% | Daily target | Daily target reached |
| Cold | 8% | 50% of daily target | 3 consecutive losses |

### Rule: Float-Based Hard Caps

| Float Range | Max Shares (any single entry) | Max Total (all adds) |
|---|---|---|
| Sub-1M | 2,000 | 5,000 |
| 1M–3M | 7,500 | 15,000 |
| 3M–10M | 5,000 | 10,000 |
| 10M+ | 2,500 | 5,000 |

### Rule: Daily Circuit Breakers

```python
CIRCUIT_BREAKERS = {
    "max_daily_loss_pct": 0.03,        # stop trading if down >3% of account
    "consecutive_losses": 3,           # stop or halve size after 3 in a row
    "post_big_win_decay": True,        # reduce size on 2nd trade after >2× goal
    "time_cutoff": "11:00 ET",         # no new entries after this time (default)
    "extended_time_cutoff": "13:00 ET" # only valid on hot days with cushion >2× goal
}
```

### Rule: Post-Loss Recovery Sizing

After a day where max_daily_loss_pct was hit or exceeded:
- Day 1 after: 50% of normal size until daily cushion reaches 50% of the loss
- Day 2+ after: 75% of normal size until full recovery
- Full size resumes: when account balance is back above pre-loss level

After a single trade loss >$2,000 (normal account stage):
- Complete stop for at least 30 minutes
- Resume at 50% size for remainder of session
- Log the reason for the loss before resuming

---

## Summary: The Core Sizing Principle

Ross's position sizing can be described in one sentence: **build a cushion first, then expand into strength, then de-risk as the move extends.**

This means:
1. Initial entry is always smaller than what the account could theoretically support
2. Size expands only after profit is locked in — never in anticipation of profit
3. As a stock moves into extended territory (parabolic, wide spreads, late in the day), position is reduced regardless of open profit
4. One bad day does not justify a larger next-day position to recover — it justifies a smaller one

The 56% appearance rate of sizing in session summaries, and the 274 scaling add-on mechanics across 5,010 trades, confirms this is not an afterthought. It is the primary execution skill separating profitable sessions from catastrophic ones.
