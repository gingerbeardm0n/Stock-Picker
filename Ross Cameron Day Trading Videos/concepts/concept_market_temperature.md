# concept_market_temperature.md
# jTrader Concept: Market Temperature

**Last Updated**: 2026-05-06
**Source**: Pass 1 enrichment FILES 0001-1799 + qualitative analysis of TRANSCRIPT_SUMMARIES_0001-0199
**Status**: Active — drives parameter adjustment logic

---

## Overview

Market temperature is Ross Cameron's primary context filter — the first question he answers each morning before sizing or selecting setups. It is not a momentum indicator. It is a classification of how the entire market is behaving that day, expressed as a binary (hot vs. cold) with a degenerate case (chop day).

The 1:2.7 hot:cold ratio across 1,799 sessions is the most important single fact about this concept:
- Hot days (~261 files): Ross trades aggressively, holds longer, scales larger
- Cold/slow/choppy days (~714 files): Ross trades defensively, takes only A+ setups, exits faster, often takes one small green day and stops

This ratio means the default operating mode is cold-market discipline. Hot market behavior is the exception, not the rule.

---

## 1. What Is Market Temperature

### Hot Market Definition

Ross uses the following terms interchangeably to describe hot markets:
- "hot market", "hot tape", "momentum day", "strong momentum"
- "market is on fire", "really good day", "everything is working"

Operational definition: A hot market is one where multiple stocks move 30%+ intraday with high relative volume, gap scanners show strong pre-market action, and setups that normally fail are following through.

Characteristics observed across hot-day summaries (FILES 0003-0122):
- Leading gapper is up 50%+ pre-market with news catalyst
- Multiple stocks hitting high-day-momo scanner before 9:30 AM
- First 5-minute candle makes new high and holds
- Halts are predominantly halt-up (circuit breaker on upside)
- P&L targets are exceeded within 30-60 minutes of open
- Ross uses phrases like "this is a stock I've been waiting for"

Examples:
- FILE 0003: LUCY up, "hot market", volume high — +$12,553, session ended 10:30 secured
- FILE 0007: ENSC biotech news, "hot market", volume high — +$26,553
- FILE 0011: DRUG + PEGGY + SOBR running simultaneously, "hot market" — +$40,854
- FILE 0114: HOLO (3000%), SYRA, HKIT all running same day — "hot market", volume high

### Cold Market Definition

Ross uses these terms for cold markets:
- "cold market", "slow day", "choppy", "chop day", "difficult day"
- "not a lot of opportunity", "grinding small profits", "base hits day"
- "market attention scattered", "no clear dominant setup"
- "bear market feel", "slow tape", "lower quality setups"

Operational definition: A cold market is one where the gap scanner shows weak pre-market action (leading gapper up only 10-20%), few stocks qualify on all criteria simultaneously, and setups that trigger often fail to follow through.

Characteristics observed across cold-day summaries:
- Leading gapper is up only 10-30% pre-market, often without news
- Scanner shows only 1-2 stocks worth watching vs. 4-6 on hot days
- First candles are choppy — multiple false breakouts
- When Ross enters, stocks frequently flush back to entry or below
- P&L accumulates slowly — the day's peak might be $1,000-$3,000
- Session often ends at 10:00-10:30 AM with "one trade and done"

Examples:
- FILE 0102: GDC was the only real setup, "cold market" — +$2,071
- FILE 0105: SIDU and DTSS, "cold market", bear market focus — +$2,045
- FILE 0110: SPRB 130% gap but slow day, "cold market", volume low — +$1,131 (described as "short share size kind of day")
- FILE 0116: UNCY only trade, "cold market", volume low — +$356, noted "could have been a no-trade day"
- FILE 0510: Market "relatively cold", grinding rather than home runs — +$2,600
- FILE 0522: "trader rehab" after $65K loss week, "cold markets, defense over offense" — +$889

### "Chop Day" — The Degenerate Case

A chop day is a subset of cold market where setups trigger but immediately reverse. Ross uses this to describe days where:
- Multiple entries fail in sequence within the first 30 minutes
- Win rate drops below 50% on what look like valid setups
- Each entry is stopped out but the move happens after the stop

FILE 0111 is a textbook chop day: leading gapper SLNG "failed immediately, signaling a choppy day ahead." Ross took 5 trades, 2W-3L, called it "extremely choppy Thursday where multiple trade setups became traps." Session ended at 10:00 AM.

FILE 0119: WLDS consumed most of the session with repeated failed breakouts. "Knocked himself out of the game early." 2W-2L record.

Ross's stated rule on chop days: if the first trade fails immediately (flushes through the setup level without follow-through), downgrade to chop-day mode and reduce size to minimum.

---

## 2. How to Detect Market Temperature in Real Time

### Premarket Indicators (4:00 AM – 9:15 AM)

These are the signals Ross evaluates before the open to classify the day:

**Primary: Gap Scanner Quality**

The gap scanner is the first signal. Ross explicitly checks it pre-market and makes comments like "pathetic gap scan" (FILE 0103 — leading gapper only up 20% at 6:45 AM, described as making him "reluctant to sit down") vs. "scanner lit up" on hot days.

| Condition | Temperature Signal |
|-----------|-------------------|
| Leading gapper up 50%+ with news catalyst | Hot |
| Leading gapper up 30-50%, no catalyst | Neutral-warm |
| Leading gapper up 10-30%, weak or no catalyst | Cold |
| Gap scanner showing 0-1 tradeable stocks | Cold / possible no-trade day |

**Secondary: Number of Stocks on Watchlist**

Hot days generate 4-8 stocks worth watching. Cold days generate 1-3. If Ross's morning watchlist only has 1-2 names, that is a cold signal.

**Tertiary: Pre-Market Volume and Price Action**

- Heavy pre-market volume with clean trend = hot signal
- Choppy pre-market price with thin volume = cold signal
- Stock that gapped 200%+ but already faded 50% from high by 9:00 AM = cold signal (move is "already started", FILE 0003 re: BCDA)

**Sector Heat**

Multiple stocks from the same sector gapping = amplified hot signal (biotech news sparks sympathy plays, Chinese stocks run in sympathy, crypto names all move together). Sector heat appeared in FILES 0113 (KPRX + SQL both running), FILE 0114 (Chinese stocks), FILE 0122 (MEDS + GLTO sympathy).

### Early Tape Signals (9:30 AM – 9:45 AM)

The first 15 minutes confirm or override the pre-market read.

**First Candle Behavior**

Ross explicitly watches the first 1-minute and 5-minute candles:
- First candle makes new high and holds above it = hot/strong confirmation
- First candle spikes and immediately reverses = cold/chop warning
- FILE 0111: "leading gapper SLNG failed immediately, signaling a choppy day ahead"

**Volume at Open**

Hot days: opening volume is dramatically higher than pre-market averages. The scanner fills with stocks immediately.
Cold days: opening volume is thin. Spreads are wider. Ross explicitly mentions stocks with "thick spreads" and "spoof orders" as cold signals (FILE 0005 re: TWG).

**Halt Behavior**

Halt-up circuit breakers on the first 30-100% move = strong hot signal.
Halt-down in the first 15 minutes = cold signal. Ross interprets early halt-downs as evidence of trapped buyers and weak follow-through.

**MACD State on Leading Stock**

Ross checks MACD on the leading stock's 1-minute chart early. Positive MACD with price above VWAP = hot signal. Negative MACD diverging = cold signal even on a seemingly hot stock.

---

## 3. Hot Market Rules

### Setup Selection

On hot days, Ross expands the setup universe. The following setups all produce above-average results on hot days:
- Gap and go (primary): enter on first pullback or first 5-min candle new high
- News-driven momentum: biotech approvals, reverse splits, uplist/IPO
- Sympathy plays: sector moves create secondary opportunities
- Dip trades: all dip trades have higher success rate when market is hot

Ross explicitly takes lower-quality setups on hot days. FILE 0003: BCDA was a "lower quality setup" but he still entered because "momentum clustering as market heated up." FILE 0011: ATNF was "technically a lower-quality setup but profitable nonetheless" during a hot session.

He also trades more stocks per session. Hot days often have 3-7 individual stock positions vs. 1-3 on cold days.

### Position Sizing

Hot market sizing behavior from summaries:
- Full standard position size or larger
- Aggressive scaling: add on breakouts, add on dips, pyramid into momentum
- FILE 0004: WETG — seven separate entries, position scaled from 2K to 4.5K shares at highs
- FILE 0007: ENSC — maxed at 4,500 shares through multiple adds; "front-loaded early when MACD confirmed"
- FILE 0011: DRUG — "scaled in heavily" up to 4,000 shares through halt-up scenarios

The pattern: start with a smaller anchor position, add as the move confirms, scale back as it extends. Ross explicitly does NOT go max size at entry on hot days — he starts smaller and adds.

### Hold Duration

Hot days allow longer holds. Ross stays in positions through:
- Multiple halt-up cycles
- 30-60 minute holds (vs. 5-15 minute holds on cold days)
- Multiple full re-entry cycles on the same stock

Key signal to exit even on hot days: MACD negative cross at highs. Ross uses this explicitly in FILES 0002, 0007, 0012. When MACD goes negative near the day's high, he exits the full position regardless of how hot the day is.

### Behavioral Risks on Hot Days

Hot market sessions show the highest frequency of behavioral deviation in the metadata:
- FILE 0011: "oversize and overtrading" — gave back $12K on DRUG at highs
- FILE 0114: "FOMO-entry and revenge-trade" — gave back $3,000 of $6,500 peak
- FILE 0012: "FOMO-entry" — attempted to chase moves past prime entry window

Ross's stated rule: set a profit stop (e.g., "if I give back $2,000 from peak, I close everything"). Hot market FOMO is the primary cause of turning large winners into small ones.

---

## 4. Cold Market Rules

### Setup Selection: A+ Only

The most consistent cold-market rule across all summaries: trade only the single best setup available, not second-best or third-best options.

Ross's language on cold days:
- "No compelling setups" → no trade (FILE 0116)
- "Market attention scattered across multiple stocks with no clear dominant setup" → one small trade (FILE 0116)
- "Not a market for hero trades, grinding small profits" (FILE 0112)
- "Cold markets, defense over offense, small consistent wins over home-run chasing" (FILE 0522)
- "Short share size kind of day" (FILE 0110)

A+ criteria on cold days are stricter:
1. Must have news catalyst (not just technical setup alone)
2. Float must be small (sub-5M preferred, sub-1M ideal)
3. Relative volume must be 3x+ on a cold day (vs. 2x acceptable on hot day)
4. Pattern must be clean — no ambiguity on entry level
5. Pre-market trend intact (not already reversed from gap high)

If the leading gapper fails criteria 1-3, Ross either skips entirely or takes 1 small scalp and exits immediately.

### Position Sizing on Cold Days

Cold day sizing behavior across summaries:
- Reduced share count (Ross explicitly says "reduced" in metadata across cold-day sessions)
- No scaling into position — starter position only, no adds
- Maximum 1 add if the setup confirms strongly
- Earlier partial profit-taking (sell 50% at first target vs. holding through full move)

FILE 0110: "short-share-size kind of day" — stayed conservative.
FILE 0117: "multiple small wins, locked green day rather than pushing into ZURA's light volume halt setup."
FILE 0522: Post $65K loss, "5,000 share cap" during cold market recovery phase.

The practical formula: cold day size = hot day size × 0.5 or less.

### Exit Timing on Cold Days

Earlier exits on cold days. Specific rules observed:
- Take profits at first target (T1), do not hold for T2 or T3
- If stock hesitates at resistance for more than 2-3 candles, exit
- Do not hold through halts on cold days — resume price is unpredictable and cold-day stocks often halt-down
- 10:00-10:30 AM is the hard stop on cold days (vs. optional stop on hot days)

Ross's stated logic: "on slow days, morning momentum is gone by 10:30, there's no reason to stay in." Multiple cold-day sessions end at 10:00-10:30 AM.

### Cold Day Acceptable Outcomes

Ross explicitly reframes success on cold days:
- Small green day ($200-$2,000) = success
- One trade and done = acceptable
- Zero trades = acceptable if no A+ setup appears

FILE 0116: +$356 on one trade, "this could have been a no-trade day." The framing matters — Ross was satisfied with this outcome.

FILE 0110: +$1,131, "successful because stayed out of trouble by trading conservatively."

---

## 5. Chop Day Rules

### When to Declare a Chop Day

Three signals trigger a chop day declaration:
1. First 1-2 trades fail on what look like valid setups (entries triggered but immediately reversed)
2. Leading stock shows multiple false breakouts within first 15 minutes
3. 2-3 consecutive losses in first 30 minutes of trading

FILE 0111: "The leading gapper SLNG failed immediately, signaling a choppy day ahead." This was the trigger — one failed leading gapper at open = elevated chop probability for the whole session.

### Chop Day Response Protocol

Observed behavior across chop day sessions:

**Immediately after declaring chop:**
- Stop adding to any losing position
- Reduce share size to minimum (25-50% of cold-day size)
- Wait for one clear setup — do not trade out of frustration

**During the chop session:**
- Only trade breakouts that come out of extended consolidation (flat base, not choppy back-and-forth)
- Avoid any pattern that has already failed once on that stock today
- Skip second and third entries on the same stock if first failed
- File 0117: "wisely locked in the green day rather than pushing into ZURA's light volume halt setup"

**Stop condition:**
- 3 consecutive losses → stop for the day
- Max loss hit (account-level) → mandatory stop
- Ross explicitly mentions a "three-loss rule" — three consecutive losses ends the session regardless of time of day

### What Chop Days Cost

The worst outcomes in the data are almost all cold/chop days where Ross overrode the chop signal and continued trading:
- FILE 0519: Chop day + revenge trading = -$11,318 (hit max loss, called broker to increase limit mid-day)
- FILE 0521: Multiple cold signals ignored, oversized DLPN revenge trade = -$65,000 (career worst at time)

Ross's reflection from FILE 0521: "in a cold market with poor setups, he was forcing trades, oversizing in revenge, and ignoring the fact that three consecutive down days was signaling a shift in market regime."

The lesson: chop day signals are warning signals for the entire current market regime, not just a single session. Three consecutive red or near-red days in the metadata is Ross's signal for "trader rehab" — dramatically reduced size and max loss until confidence rebuilds.

---

## 6. jTrader Implementation

### Temperature Detection Signals

The following signals should be computed and combined into a temperature score:

**Pre-Market Score (computed at 9:15 AM)**

```python
temperature_premarket = (
    leading_gapper_pct,          # gap % of best scanner stock
    has_news_catalyst,            # boolean from news scan
    num_stocks_on_scanner,        # count of stocks meeting base criteria
    premarket_volume_ratio,       # today premarket vol / avg premarket vol
    sector_sympathy_count         # how many stocks in same sector gapping
)
```

Thresholds derived from data:
- `leading_gapper_pct >= 50%` + `has_news_catalyst == True` + `num_stocks >= 3` → HOT candidate
- `leading_gapper_pct >= 20%` + one of the above → NEUTRAL candidate
- `leading_gapper_pct < 20%` OR `num_stocks <= 1` → COLD

**Open Tape Score (computed 9:30-9:45 AM)**

```python
temperature_open = (
    first_5min_candle_made_new_high,    # boolean
    opening_volume_vs_premarket,         # ratio
    halt_direction_first_halt,           # "up" / "down" / None
    leading_stock_macd_state,           # "positive" / "negative" / "neutral"
    first_trade_outcome_if_taken        # "win" / "loss" / None
)
```

Combining premarket + open tape:
- Both scores = hot → **HOT** mode
- Premarket hot + open choppy → watch for one more candle, default to NEUTRAL
- Both scores = cold → **COLD** mode
- First trade fails with clean setup → upgrade to CHOP warning

**Runtime Temperature Updates**

Temperature is not static. jTrader should update it based on:
- First trade result: loss on clean setup → downgrade temperature
- 2 consecutive losses → force COLD mode regardless of premarket
- Leading stock halts down in first 30 minutes → force COLD mode
- MACD negative on leading stock below VWAP before 9:45 → COLD

### Parameter Adjustments by Temperature

| Parameter | HOT | NEUTRAL | COLD | CHOP |
|-----------|-----|---------|------|------|
| max_position_pct | 20% | 15% | 10% | 5% |
| setup_quality_min | 3/5 | 4/5 | 5/5 (A+ only) | 5/5 + news required |
| add_on_allowed | yes (2 adds max) | yes (1 add) | no | no |
| t1_hold_through | yes (target T2) | yes (target T1) | no (exit at T1) | no (exit early) |
| hold_through_halt | yes | caution | no | no |
| max_trades_per_day | 10+ | 5 | 3 | 1 |
| session_stop_time | 12:00+ | 11:00 | 10:30 | 10:00 |
| daily_loss_limit_pct | 3% | 2% | 1.5% | 1% |
| consecutive_loss_stop | 4 | 3 | 2 | 1 |

### Chop Day Detection Logic

```python
def detect_chop_conditions(session_state):
    """
    Returns True if chop day conditions are met and trading should pause/stop.
    """
    if session_state.consecutive_losses >= 2:
        return True
    if session_state.first_trade_was_false_breakout:
        return True
    if session_state.leading_stock_false_breakouts_in_15min >= 2:
        return True
    return False
```

When `detect_chop_conditions()` returns True:
- Immediately reduce `max_position_pct` to 5%
- Set `add_on_allowed = False`
- Set `consecutive_loss_stop = 1` (next loss ends the day)
- Log "CHOP DAY MODE ACTIVATED" with timestamp

### Cold Day No-Trade Decision

jTrader should implement a pre-trade gate that blocks entry if:
- Temperature is COLD and the setup does not meet A+ criteria
- A+ criteria = gap 50%+ AND news catalyst AND float < 5M AND relative volume > 3x

If no setup meets this criteria by 9:45 AM on a cold day, jTrader should log "No A+ setup found, skipping session" and not enter any trades.

This matches Ross's behavior in FILE 0116 (one tiny trade then done) and FILE 0522 (one carefully screened trade after cold scan). The cost of skipping is one flat day. The benefit is avoiding the chop-day cascade that produced the largest losses in the dataset.

### Temperature Logging

Every session should log the temperature classification and key signals:

```
SESSION_START: 2026-05-06
Premarket_temperature: COLD
  leading_gapper: AABC +23%, no news
  scanner_count: 2 stocks
  premarket_volume_ratio: 0.8x

Open_tape_update: 09:35 COLD CONFIRMED
  first_candle: false_breakout on AABC
  halt_direction: none
  macd_state: negative

Mode: COLD
Active_params: max_position=10%, max_trades=3, stop_time=10:30
```

This log enables post-session analysis: correlate temperature classifications against actual P&L outcomes to validate and tune the thresholds above.

---

## Key Takeaways for jTrader

1. **Cold is the default**. 2.7x more cold days than hot days means jTrader runs in COLD mode most of the time. Hot mode is activated by evidence, not assumed.

2. **Temperature determines everything else**. Setup selection, position size, hold duration, and session length are all downstream of temperature. Get temperature wrong and every other parameter is calibrated for the wrong regime.

3. **The first failed setup is a temperature signal**. A clean setup that fails immediately on a stock that should have worked is evidence the tape is cold. Do not retry. Reduce size and wait.

4. **Chop days produce the biggest losses in the dataset**. NOT because Ross traded larger — but because he didn't stop when chop conditions appeared. jTrader must hard-stop at `consecutive_loss_stop` threshold.

5. **Cold day success is defined differently**. One trade, $500 green, session ends at 10:15 AM = excellent cold day. The goal is not to equal hot day P&L — it is to not give back hot day gains.

6. **Three consecutive red days = market regime shift**. If jTrader shows 3 red or near-red days in a row, force a reset: cut max_position_pct by 50%, do not restore until 3 consecutive green days. This is Ross's "trader rehab" pattern applied as an algorithmic rule.
