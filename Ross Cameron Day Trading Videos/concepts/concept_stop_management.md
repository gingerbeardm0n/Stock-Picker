# Concept: Stop Management
**Last Updated**: 2026-05-06
**Source**: Pass 1 enrichment, FILES 0001–1799 (5,010 trades)
**Status**: Active — use for jTrader exit logic implementation

---

## 1. Stop Philosophy

Ross's core position: losses are a cost of doing business, not a failure — **provided they are small and deliberate**. The danger is never a single stop; it is a sequence of stops that compound into an account-breaking drawdown.

Key principles observed across summaries:

- **Stops are pre-planned, not reactive.** Entry and stop are decided simultaneously. FILE 0103: "His profitable stop was tied to $10.50, allowing him to sleep." A stop that requires a decision at the moment of pain is already too late.

- **Base hits over home runs forces tight stops by design.** FILE 0001: averaging $1.8k/day, 9,000 shares, strict 9:30–10:30 AM window. Small, high-probability bites make a $0.10–0.20 stop viable. Wide stops imply a hope trade.

- **Smaller size makes exits cleaner.** FILE 0104: "Ross emphasized how smaller size makes it easier to exit emotionally without fighting slippage; with bigger positions he risks becoming married to them." Size and stop discipline are inseparable.

- **The daily max loss exists as a circuit breaker, not a target.** When stops consume the daily max, trading stops entirely. FILE 0111 (SPRO, 20,000 shares): after three consecutive stops he "ended at 10 AM with just $1,075 in profit, exhausted and wanting to protect himself from further damage."

- **Profit stops are a legitimate and frequently used tool.** Once a meaningful cushion is built (typically at or above daily goal), the stop migrates to a level that guarantees a green day. FILE 0103 session ended at 10:21 "profit stop hit" after a +$10,025 day. This is not weakness — it is the mechanism that produces consistent green months.

---

## 2. Stop Types Taxonomy

### 2.1 Loss Stops (Protect Capital)

Used when the trade hypothesis is invalidated. The position has not been profitable or is quickly going red.

| Sub-type | Trigger | Typical Magnitude |
|---|---|---|
| **Reversal stop** | Price action reverses vs. entry direction | Most common — 433 occurrences |
| **Failed-breakout stop** | Breakout triggers but price fails to follow through, reverses back below level | 208 combined occurrences (2nd most common) |
| **False-breakout / trap stop** | Level breaks briefly, then reverses sharply; entry is trapped | 17 occurrences, high-damage potential |
| **Halt-down stop** | Stock halts downward; resumes lower, confirms reversal | 15 occurrences |
| **Resistance stop** | Clear seller wall prevents advance; exit before loss compounds | 28+ occurrences (resist + resistance) |
| **Support-level stop** | Key support level breaks definitively | 24 occurrences |

### 2.2 Profit Stops (Lock Gains)

Used when in a winning position to guarantee a minimum outcome. The stop is raised as price advances.

| Sub-type | Trigger | Notes |
|---|---|---|
| **Profit-scale** | Scale out portions at T1, T2, T3 resistance levels | 60 occurrences — primary method |
| **Profit-target** | Full exit at predetermined target | 111 occurrences — used on scalps |
| **MACD divergence exit** | MACD turns negative while price attempts new highs | Files 0002, 0007 — signals end of momentum |
| **Spreading / volume decline exit** | Spreads widen, bid volume falls | FILE 0004: "risk management required reducing size as price extended" |
| **Sellers stacking exit** | 25–50k share seller blocks appear | FILE 0002: "stopped when sellers stacked 25–30k share blocks" |
| **Daily-goal lock** | Hit daily target, raise stop to protect green day | Most common session-end driver |

Together, profit-scale + profit-target = **171 exits** (34% of all coded exits). A large fraction of "stop criteria" events are actually disciplined profit-taking, not losses.

### 2.3 Time Stops

Used when the trading window closes or momentum dissipates, regardless of position P&L.

| Sub-type | Trigger | Notes |
|---|---|---|
| **10:30 AM cutoff** | Hard wall — no new positions after 10:30 ET | FILES 0006, 0009: "profit secured before 10:30 AM threshold" |
| **11:00 AM rule** | Morning momentum considered exhausted | Observed across multiple files; aligns with time-decay exit logic |
| **MACD-negative time decay** | MACD turns negative + price extended = no re-entries | FILE 0007: "secondary post-MACD entries failed due to insufficient dip depth" |
| **Scalp duration exceeded** | A scalp that is not working within 1–3 minutes is abandoned | HOLD_DURATION: scalp = sub-2-min expectation |

---

## 3. Per-Pattern Stop Rules

### 3.1 Gap-and-Go
- **Stop**: Below the candle that triggered entry, or below the nearest half-dollar/whole-dollar support (whichever is tighter).
- **Logic**: A proper gap-and-go entry is on or just after a breakout candle. If price returns below that breakout candle, the move has failed.
- **Examples**: FILE 0010 (FTNW): hesitated on dip to $3.20, waited for confirmation, entered $3.40. Stop below the $3.20 dip low.

### 3.2 Flat-Top Breakout
- **Stop**: Below the flat-top resistance line that was just broken (now support).
- **Logic**: The flat-top is confirmed only if price holds above the break level. Return below it = false breakout.
- **Examples**: FILE 0008 (GNC): entered $4.46–4.47 on flat-top consolidation. Stop below $4.40 support.
- **Additional risk factor**: Wide floats on flat-tops = "float concerns" — reduce size, accept tighter profit target.

### 3.3 Micro-Pullback / Dip Trade
- **Stop**: Below the dip low (the candle that created the pullback entry).
- **Logic**: The dip trade thesis is that the pullback is temporary and higher prices follow. If the dip low breaks, the structure is broken.
- **MACD dependency**: FILE 0002: "dip trades worked well when MACD was positive." When MACD is negative, skip dip entries entirely.
- **Examples**: FILE 0007 (ENSC): entry at $2.90 micro pullback. Stop below prior dip candle. Trade ran $2.90→$5.20.

### 3.4 ABCD / Ascending Support
- **Stop**: Below the prior higher low (the C-point in ABCD, or the last touch of the ascending trendline).
- **Logic**: If ascending support breaks, the structure is broken. Do not hold hoping for a V-reversal.
- **Examples**: FILE 0111 (SPRO): ascending support trendline at $2.05; stop triggers on reversal below $2.00. Loss -$2,000 after 20,000-share oversize.

### 3.5 Halt-Resume
- **Stop**: Immediately if first candle post-resume fails to make a new high; or if the stock resumes into a halt-down scenario.
- **Logic**: Halt-resume trades are binary. First candle post-resume either confirms continuation or it does not.
- **Examples**: FILE 0006: "halt strategy involved re-entry after the first candle to make new highs post-halt." FILE 0114 (SYRA): halt-down reverse = immediate stop, -$500.

### 3.6 News-Driven / Breakout Squeeze
- **Stop**: Below VWAP, or below the prior consolidation base.
- **Scaling logic**: As the move extends, reduce position size. FILE 0004 (WETG): "reducing position size as price extended (4k shares down to 1.5k at highs) due to wider spreads and elevated volatility."
- **MACD exit**: When MACD crosses negative at highs, exit remaining position. This applies regardless of whether the price has reversed yet (leading indicator).

### 3.7 Dip-Buy Off VWAP
- **Stop**: Below VWAP by a defined buffer ($0.05–0.15 depending on stock price).
- **Logic**: The dip-buy thesis is that VWAP is support. If VWAP fails, the long thesis fails.
- **Examples**: FILE 0103 (BFRG): dip off VWAP, halt-down resume reversed — loss -$1,300 triggered profit stop on the overall session.

---

## 4. Hold vs. Bail Decision Framework

This is the highest-judgment call in the system. The data from 5,010 trades shows that the biggest single-day losses (e.g., FILE 0114: -$3,000 on SYRA; FILE 0118: -$4,000 on VERU) almost always involve holding or adding into extended moves with deteriorating structure.

### Hold is justified when ALL of these are true:
1. **MACD is still positive** (not just green, but trending up or flat positive)
2. **Price is making higher lows** on 1-minute chart (structure intact)
3. **No seller wall visible** at the next level (no 25k+ blocks on Level 2)
4. **Halt was halt-up, not halt-down** (continuation signal vs. reversal signal)
5. **Time is before 10:30 AM** (within the high-probability window)
6. **Position is already scaled** (half or more taken off at T1 — house money effect)

### Bail immediately when ANY of these occur:
1. **Halt-down** — resuming below halt trigger price: exit first candle, no waiting
2. **MACD crosses negative** while price is near highs or extended: exit, no re-entry
3. **Sellers stacking (25k+ blocks)** at ask that absorb multiple buying candles
4. **Price returns below entry candle** on a non-dip-trade (not a pullback — a failure)
5. **Third consecutive failed breakout attempt** at same level: FILE 0119 (ICU): "added for breakthrough on a red candle, lost $1,500 when the stock flushed down 50 cents"
6. **Second stop on same symbol in same session**: FILE 0114 pattern — each successive SYRA re-entry lost more
7. **Daily max loss threshold approaching** (typically $1k–$3k depending on account size)

### Special case — "Knife down":
FILE 0114 (HKIT): "vicious knife move down to $6.27 from $7.50 cost him nearly $2,000 when he added into the drop trying to catch a bounce." The knife-down pattern — fast, continuous red candles with no wick support — is never a dip-buy opportunity. Bail immediately on a knife pattern; do not add.

### Averaging down is categorically prohibited:
FILE 0118 (VERU): "he admitted that averaging down is risky" and turned a winning trade into a -$4,000 loss. The only exception is a deliberate scaling-in plan established before entry with total risk pre-calculated. Reactive averaging down (adding because the position is losing) = behavioral deviation.

---

## 5. Common Mistakes (From Summaries)

### 5.1 Chasing Extended Moves
**Pattern**: Stock already up 100–300%, entry is late in the move, stop is wide because price is extended.
**Example**: FILE 0011 (DRUG at $39–42): after two profitable trades on DRUG, Ross entered a third time at extended levels near resistance, gave back $12,000.
**Rule**: After two profitable trades on the same mover, max one more small re-entry. Three-trade fatigue on the same symbol is a documented losing pattern.

### 5.2 Fighting Seller Walls
**Pattern**: Stock stalls at a level with visible large sellers; entering/adding hoping they absorb.
**Example**: FILE 0008 (CNET): "observed 60k seller at $4.80, opting out rather than fighting supply."
**Rule**: When a 25k+ seller wall absorbs 2–3 buying candles without clearing, treat it as a resistance stop. Exit, do not add.

### 5.3 Re-entering After Time-Decay Exit
**Pattern**: Exit a position at 10:30–11:00 AM, then re-enter the same stock because it is still moving.
**Rule**: Once time-decay criteria are met (11 AM, MACD negative, post-10:30), the symbol is closed for new entries that day. FILE 0006: profits locked before 10:30 "protecting gains."

### 5.4 Oversizing Into Breakouts That Fail
**Pattern**: Large position on a breakout that immediately reverses.
**Example**: FILE 0111 (SPRO): 20,000 shares at $2.05 anticipating $2.15 breakout, stock reversed — "poor 1:1 risk-reward" — loss -$2,000.
**Rule**: Initial starter position on breakout, not full size. Scale only into confirmed follow-through (not anticipation).

### 5.5 Trading After a String of Losses
**Pattern**: Continue trading after 2–3 consecutive stops in the same session.
**Example**: FILE 0111: "ended at 10 AM... exhausted and wanting to protect himself from further damage." FILE 0114: successive SYRA entries each worse than the last.
**Rule**: After two losses on the same symbol in a session, that symbol is banned. After three total losses in a session, consider stopping for the day regardless of whether daily max is hit.

### 5.6 Ignoring MACD at Exits
**Pattern**: MACD turns negative, but trader holds because price has not yet reversed.
**Example**: FILE 0007 (ENSC): "MACD remained positive throughout the main squeeze but turned negative near highs, providing an exit signal. Divergence between bearish MACD and price attempting $4.50–$5.00 resistance prompted him to avoid chasing into weakness."
**Rule**: Negative MACD at or near highs = close 75% or more of position. The reversal signal leads price; waiting for price confirmation is too late.

### 5.7 Low-Float Cheap Stocks With High Commission Drag
**Example**: FILE 0119 (WLDS): "trading low-priced stocks like WLDS with 20,000–40,000 shares and 10–15 trades incurs ECN fees of $0.003/share, meaning $120 in fees per round-trip on a 20,000-share order. These costs consumed 25–30% of his daily profit."
**Rule**: For stocks under $2.00, each round-trip stop carries significant commission drag. Tighter actual stops, fewer re-entries, or skip entirely.

---

## 6. jTrader Implementation Rules

These are the concrete, codeable rules derived from the above analysis.

### 6.1 Loss Stop Placement (at entry)
```
FLAT_TOP:       stop = flat_top_level - $0.02 (below the broken resistance, now support)
GAP_AND_GO:     stop = entry_candle_low - $0.01
MICRO_PULLBACK: stop = dip_candle_low - $0.01
ABCD:           stop = C_point_low - $0.01
VWAP_DIP:       stop = vwap - $0.10 (buffer for spread noise)
HALT_RESUME:    stop = halt_trigger_price - $0.05 (tight; exit on first candle failure)
NEWS_BREAKOUT:  stop = vwap or prior_consolidation_base - $0.05
```

### 6.2 Profit Stop Migration
```
After T1 hit (first target):
  - Cover 33–50% of position
  - Raise stop to breakeven or slightly above entry

After T2 hit (second target):
  - Cover 25% more
  - Raise stop to T1 level

After T3 or extended:
  - Scale remaining to 25% or less
  - Stop is now trailing at prior 5-min candle low
```

### 6.3 MACD Exit Override
```
IF macd_histogram < 0 AND position_is_open AND price >= entry_price:
    IF position_is_profitable:
        exit 75% of remaining shares immediately
        hold residual 25% with tight trailing stop
    ELSE:
        exit 100% (stop was already triggered)
```

### 6.4 Daily Max Loss Circuit Breaker
```
DAILY_MAX_LOSS = account_balance * 0.02   (2% of account, configurable)

IF daily_realized_loss >= DAILY_MAX_LOSS:
    close all open positions
    block new entries for remainder of session
    log: "DAILY_MAX_LOSS_HIT"
```

### 6.5 Profit Stop (Daily Goal Lock)
```
DAILY_GOAL = account_balance * 0.01       (1% of account, configurable)

IF daily_realized_profit >= DAILY_GOAL:
    SET session_profit_floor = daily_realized_profit * 0.50
    IF current_open_positions_P&L causes daily_profit to drop below session_profit_floor:
        close all positions
        log: "PROFIT_STOP_HIT"
```

### 6.6 Symbol Cooldown Rules
```
IF symbol had reversal_stop AND re-entry_attempted within same session:
    second_entry_allowed = true     (one retry allowed with reduced size, 50%)
    third_entry_blocked = true      (hard block same session)

IF time_decay_exit_logged for symbol:
    new_entries_blocked = true      (no re-entry after 11 AM exit, same day)
```

### 6.7 Halt-Down Immediate Exit
```
ON halt_type == "HALT_DOWN":
    EXIT all shares at market on first tradable price post-resume
    DO NOT wait for a bounce candle
    DO NOT average in on halt-down resume
```

### 6.8 Knife-Down Block
```
IF consecutive_red_candles >= 3 AND candle_bodies_increasing_in_size:
    BLOCK dip-buy entry on this symbol for 10 minutes
    IF already in position: exit immediately, no averaging
```

### 6.9 Seller Wall Resistance Stop
```
IF level2_ask_size >= 25000 AND price_failed_to_clear_for >= 2_candles:
    exit_position OR reduce to starter size
    block adds until seller wall clears
```

### 6.10 Time Window Enforcement
```
NEW_ENTRY_CUTOFF = 10:30 ET (configurable)
TIME_DECAY_EXIT  = 11:00 ET

AT 10:30 ET: block all new entries
AT 11:00 ET: begin exiting any remaining positions at next favorable candle
AT 12:00 ET: force-close all remaining positions at market
```

---

## Appendix: Stop Criteria Frequency Table (5,010 trades, FILES 0001–1799)

| Stop Criterion | Count | Category |
|---|---|---|
| reversal | 433 | Loss stop |
| failed-breakout / failed breakout | 208 (combined) | Loss stop |
| profit-target | 111 | Profit stop |
| profit-scale / PROFIT: scaled | 82 (combined) | Profit stop |
| sellers / resist / resistance | 66 (combined) | Loss stop |
| stop loss (explicit) | 26 | Loss stop |
| support level | 24 | Loss stop |
| scaling | 19 | Profit stop |
| scalp | 19 | Profit stop |
| false breakout | 17 | Loss stop |
| halt-down | 15 | Loss stop |
| reversal flush | 14 | Loss stop |

**Key ratio**: Reversal stops (433) are 2.1x more common than failed-breakout stops (208). This implies that the most frequent loss event is entering a valid breakout that then reverses — not a false breakout at the level, but a reversal after the stock initially follows through. Implication for jTrader: stops must trail as the trade moves in your favor; a static entry-candle stop is insufficient for extended moves.

**Profit exits as % of all exits**: (111 + 82 + 19 + 19) = 231 / 5,010 coded = ~4.6% of trades have explicit profit-exit coding. The actual rate is higher — many WIN rows with PROF: prefix exits are not separately tallied in the stop criteria field. The profit-exit mechanism is not a minor edge case; it is the primary exit method on winning days.
