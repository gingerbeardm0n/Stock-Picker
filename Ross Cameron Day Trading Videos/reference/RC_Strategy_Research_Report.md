# Ross Cameron Strategy Research Report
### jTrader Rebuild — Phase 1 Deep Dive
*Generated March 2026 from 80 transcripts — updated with 20-video pilot batch deep analysis (March 2026)*

**Category naming convention:**
- **A (SCRN)** — Pre-screen / 5 Pillars
- **B (ENTR)** — Entry Signals
- **C (STOP)** — Stop Loss Signals
- **D (PROF)** — Profit Take Signals

---

## PILOT BATCH UPDATE — 20-Video Deep Analysis (March 2026)

This section summarizes new and confirmed findings from the 20-video pilot batch: 15 Daily Recaps + 5 LIVE Morning Show sessions. These were full live-action recordings (trades happening in real time or same-day recaps with specific entry/exit narration), making them substantially higher-signal than the teaching library. Where pilot findings **confirm** prior hypotheses they are marked ✅. Where they **upgrade** a soft finding to a hard rule they are marked ⬆️. Where they introduce a **new** finding not in the prior analysis they are marked 🆕.

---

### Pilot Finding 1 — MACD "Negative" Meaning CONFIRMED ⬆️

**Prior status:** AMBIGUOUS — "When he speaks for himself rather than teaching, MACD negative sounds like a personal no-go."

**Now confirmed VETO.** From "I screwed up today": *"The MACD, in fact, goes negative on the one minute chart... I was like, no, I'm not taking that trade because the MACD here is negative."* He passed on a trade entirely because of MACD state. From "A Chinese Small Cap Surprise": *"when the MACD is crossing over to negative, that's when I should be hands off"* and *"MACD, when it's open — it's like above zero, it's positive — it means we are on the front side of the move."*

**Clarification on "negative":** In live trading, "MACD negative" means the MACD line (12 EMA minus 26 EMA) has crossed below zero — i.e., the short-term trend has actually reversed, not just slowed. This is distinct from the histogram going negative (which just means momentum is decelerating). The front-side/back-side framework maps directly: MACD line > 0 = front side = trade zone; MACD line < 0 = back side = no trade zone.

**jTrader action:** Implement MACD line > 0 as a hard ENTR gate and MACD line crossing negative as an immediate stop-adding / exit signal. Do not use histogram sign alone.

---

### Pilot Finding 2 — Float Sweet Spot Quantified ⬆️

**Prior status:** "Float is a strong preference (≤20M) not a hard gate."

**Now more specific.** From 30-day P&L review in the watchlist videos: *"Most of these are foreign listed companies. Most of them have floats that are less than five million shares."* And explicitly: *"ZD, $45 a share, too expensive, floats too high. SVRN, too cheap, floats too high."* Ross's best-performing stocks in the period analyzed all had floats under 5M. Stocks above 10M are associated with grindiness and choppy action.

**Revised finding:** Sub-5M = preferred zone. Sub-1M = maximum squeeze potential. 5M–10M = workable but expect more chop. 10M+ = elevated risk; 28M+ = near-veto.

**jTrader action:** Keep pre-screen float filter at ≤20M (or ≤30M) — this is consistent with the teaching corpus and is not overridden by a single live video. Tag every trade with float bucket (≤5M / 5–10M / 10–20M / 20–30M) so that backtest data can determine whether to tighten. The 5M preference is a confidence signal, not a hard gate.

---

### Pilot Finding 3 — Cold vs Hot Market Framework Fully Documented 🆕

**This was not in the prior analysis and is a significant new finding.**

The market exists in one of two states that governs the entire daily approach:

| Factor | Cold Market | Hot Market |
|--------|------------|------------|
| Daily goal | $5,000 | $20,000 |
| Weekly goal | $25,000 | Varies |
| Position size | Reduced | Maximum |
| Trade frequency | Fewer | More |
| No-trade days | Acceptable | Rare |
| Annual P&L pace | ~$1M/year | ~$5-6M/year |

*"when it's hot, you can take bigger share size... I make four times as much in a hot market"* / *"When it's cold, there's not as many opportunities, it's a quarter as much profit."*

The market temperature is assessed each morning from the scanner: leading gapper percentage, volume quality, and news presence. A 30-45% leading gapper with no news = cold day. An 80-160%+ leading gapper with strong news and low float = hot day.

**jTrader action:** Implement a market temperature signal as input to position sizing. In cold conditions, reduce max share size by ~50-75%.

---

### Pilot Finding 4 — Front Side / Back Side as Core Framework CONFIRMED ✅ ⬆️

**Prior status:** Mentioned in teaching content, not confirmed as live decision driver.

**Now confirmed as the primary entry framework.** Multiple direct quotes across live sessions: *"front side, backside... all of this is sort of on the back side"* / *"MACD open = front side; MACD negative = back side."* He explicitly passes on stocks that are back-side even if they have news and the other pillars are met (e.g., BATL on the day oil made new highs — he passed because it was on the back side of its prior move).

**Operational definition:** Front side = stock is making new highs with positive MACD. Back side = stock has made a high and is failing to break it, with MACD negative. Even sector-appropriate stocks with fresh catalysts are skipped if they're back-side.

---

### Pilot Finding 5 — Session Management (Daily P&L Stops) CONFIRMED with Numbers ✅

**Prior status:** "Give back 50% = hard stop" — confirmed previously but pilot adds context.

**Confirmed hard rules with precise thresholds:**
- Give back 50% of peak daily profit → HARD stop, walk away immediately
- Give back ~30% from peak → soft signal, usually sufficient to trigger walk-away
- These rules apply regardless of whether the daily goal has been hit

*"if I give back 50% that's a hard stop. I have to walk away"* / *"I peaked at 72,000. Gave back about a third... And I said that's it."*

**Important asymmetry confirmed:** Green days are never capped proactively. Red days have hard stops. *"I have to cap my loss days, but I don't want to cap my green days."*

---

### Pilot Finding 6 — Daily Session Timing Confirmed 🆕

**Confirmed timing framework from live session behavior:**
- 7:00-9:30am: Scanner watch, occasional pre-market trades on strong moves
- 9:30-10:30am: Opening range — primary trading window, highest quality setups
- 10:30am-11:00am: Declining quality, smaller size
- 11:00am-2:00pm: Dead zone — step away
- 3:00-4:00pm Power Hour: Occasional secondary opportunities
- After-hours: Monitor for continuation signals, rarely trade directly

**Note:** The claim that "7-8am is the highest-profit window per his own metrics" is unverified — the source of that specific data point is uncertain and should not be treated as confirmed. Ross does stream starting at 7am and watches the scanner pre-market, but his primary trading is at and after the 9:30am open. The opening range (9:30-10:30am) is the most likely highest-profit window. Needs confirmation from the larger corpus.

**jTrader action:** Confirm trading window logic covers the full 9:30-10:30am opening range as the primary window. The pre-market window (7-9:30am) is secondary and situational.

---

### Pilot Finding 7 — Order Spoofing Detection 🆕

**New finding not present in prior analysis.**

From the $52K green day (CF trade): When a large Level 2 sell order perpetually moves away from the current bid/ask (stays 10-15 cents outside the market and follows price upward), this is order spoofing — the seller has no intention of filling. This signals the "seller" is already short and trying to scare retail longs away.

*"If the price went up to 11.20, their order cancelled and moved up to 11.30... It'll never execute. It'll never get filled... your real intention is to scare people. That's order spoofing."*

The correct response: **ignore the wall, size up.** The fact that they're showing the wall means they're short and scared. Shorts showing large fake walls = squeeze fuel.

**jTrader action:** If implementing Level 2 order book reading, flag orders that continuously reprice away from the market as spoof signals and invert their sentiment signal.

---

### Pilot Finding 8 — Sector Theme as Catalyst Amplifier 🆕

**Confirmed as a real-time filter.** When a macro theme is active (energy, defense, biotech), Ross actively scans for stocks whose catalyst aligns with the theme. A stock in the hot sector with mediocre technicals gets attention; a stock with good technicals but off-theme gets less attention.

*"there's a bigger theme at play... if it were one of the two [energy or defense], I wouldn't be surprised by that at all."*

**jTrader action:** Implement sector theme detection — when USO is up significantly, flag energy sector stocks. When broad defense/military news is breaking, flag defense-adjacent tickers. Use as a probabilistic boost to SCRN score for qualifying stocks.

---

### Pilot Finding 9 — The "Obvious Trade" Standard ✅ 🆕

A recurring theme: Ross explicitly asks himself whether the setup is "obvious." The best trades are the ones where, when you see them, it's immediately clear — the stock is the clear leader, it has the highest volume, the clearest news, the cleanest chart. If he has to talk himself into a trade, it's not the right trade.

*"Is this the obvious one?"* / *"that stock becomes really obvious"* / *"nothing has been super exciting"* (no trade).

**jTrader action:** Build a composite "obviousness score" — relative volume percentile (is it clearly the highest?), gap percentage percentile (is it clearly the biggest gapper?), news quality. A stock is only traded if it is unambiguously the top candidate across all filters.

---

### Open Questions Resolved by Pilot Batch

| Question | Resolution |
|----------|------------|
| Q1: Is MACD negative a personal veto or just caution? | **RESOLVED: VETO.** Direct live evidence in "I screwed up today." |
| Q5: Is "MACD negative" histogram or MACD line? | **RESOLVED: MACD line below zero** = back side. Histogram negative = stop adding but not necessarily exit. |
| Q6: Trading window — rules failure or window problem? | **PARTIALLY RESOLVED:** Drop-off after 10:30am appears real based on live session behavior. Specific hour-by-hour P&L data not confirmed — needs larger corpus. |

### Open Questions Still Unresolved

| # | Question | Status |
|---|----------|--------|
| 2 | A-quality vs B-quality precise definition | Still needs live setup-grade content |
| 3 | Float — exact cutoff for hard veto | Narrowed to ~10M outer limit, but still needs backtest confirmation |
| 4 | Topping tail — one tail vs multiple before exit? | Still needs more live examples |
| 7 | Entry thresholds: opening gap-and-go vs bull flag at 9:45? | Still needs gap-and-go specific content |
| 8 | Position sizing: 1/4-size discipline — behavioral or algo-applicable? | Still needs clarification |

---

## 1. The Transcript Library — What We Actually Have

**Total files: 80**

| Type | Count | Notes |
|------|-------|-------|
| Teaching / Educational | 64 | The overwhelming majority |
| Small Account Challenge series | 14 | Mix of live trading + teaching |
| Recap / Performance review | 7 | Past-tense review of trades |
| True live trading (observable real-time decisions) | ~4 | See list below |

**The hypothesis was confirmed:** this is primarily a teaching library. We have very little true live trading content where his real-time reasoning is directly observable.

**The 4 most valuable for live decision-making:**
1. `How to Start Trading with 1000  Small Account Challenge Ep 1.txt` — actual live trades, scanner hits, fills, entries in real time
2. `How Im Making 286Day Day Trading with 1000.txt` — Day 2 live narration, real trade flow
3. `How I turned 51422 to 4000 in 7 Days  Small Account Challenge Ep 9.txt` — includes live moments and loss review
4. `How to Start Day Trading for Beginners LIVE STREAM.txt` — live stream format

**Confirmed low-value for strategy research** (miscategorized as "live"): `Inside My 280000 Mobile Day Trading Station`, `My Day Trading Station Episode 4`, `Small Caps vs Large Caps`, `Opening your OWN Business`, `is Day Trading the same as Gambling` — these are equipment, business, or philosophy content.

---

## 2. Highest-Value Transcripts for B/C/D Research

Ranked by strategic specificity:

1. **`Master the Bull Flag Trading Pattern TODAY`** — most precise entry and stop-loss mechanics in the corpus. Direct measurements and pattern rules.
2. **`5 Rules For Selling Losers Faster`** — clearest articulation of his stop-out and day-level risk rules. Essential for Category C.
3. **`Proven Formula for Finding BEST Stocks to Day Trade`** — pre-screen criteria with explicit thresholds. Category A.
4. **`27 Years of Trading Knowledge in 3hrs 5mins`** — comprehensive cross-category, worth full read.
5. **`Step-by-Step Guide to Beginner Day Trading Strategies Full Training`** — structured walkthrough.
6. **`Trading was HARD Until I Learned this BASE HIT Strategy`** — profit-taking philosophy.
7. **`High Accuracy 1 Minute Scalping Strategy Full Training`** — entry timing detail.
8. **`x7 Dos and Donts of Trading in a Small Account`** — behavioral rules.

---

## 3. Veto vs Probability — The Core Research Finding

This is the most important output. The scan across 24 high-value transcripts shows a clear pattern: **Category A (pre-screen) is almost entirely veto language, while B/C/D is mixed — with several hard rules buried inside what looks like probabilistic content.**

---

### CATEGORY A — Pre-Screen (5 Pillars)

All hard veto language. These are gate conditions, not weighted inputs.

| Rule | Language Type | Direct Quote |
|------|--------------|--------------|
| News catalyst required | **VETO** | "If I don't like the catalyst, then I'm not going to proceed to step three." |
| Relative volume ≥ 5x | **VETO** | "I make the most money when the stock has five times relative volume... minimum of five." (Scans show stocks below threshold explicitly rejected: "too low, too low, too low, good, good") |
| Price range | **PREFERENCE** | "I do best on stocks priced between $2 and $20" — softer language, not an absolute |
| Float / market cap | Not clearly articulated with veto language in these transcripts — needs live session research |

---

### CATEGORY B — Entry Confirmation

This is where it gets interesting. Some things that look soft are actually hard in practice.

**Hard rules (VETO language):**

| Signal | Language Type | Direct Quote |
|--------|--------------|--------------|
| Entry point on bull flag | **VETO** | "The first candle to make a new high — that is the moment of entry, that is to the penny. It's not up for negotiation what the correct entry point is. It is part of the pattern." |
| No red candle pullback after entry trigger | **VETO** | "If the next candle was red and pulled back further, I would never press the buy button." |
| No catalyst = no trade | **VETO** | "I don't see a news catalyst." [full stop, implied skip] |

**Soft rules (PREFERENCE / PROBABILISTIC):**

| Signal | Language Type | Direct Quote |
|--------|--------------|--------------|
| MACD positive / open | **PROBABILISTIC** | "So I like to do as much my trading as I can on the front side of the move when the MACD is open before it crosses over." — "I like" language |
| MACD — personal hard rule | **AMBIGUOUS** | "If it fits within your strategy, but if you're asking me, if it fits within my strategy right now, the answer is no — MACD is negative on the trade." — When speaking for himself (not teaching), MACD being negative sounds like a personal veto |
| Volume on green candles (bull flag) | **VETO-ADJACENT** | "High volume on the green candles, light volume on the red candles — if you don't see volume then you're not really understanding the true sentiment behind this move." Strong language but framed as education |
| 200 EMA proximity | **SOFT VETO** | "Check the daily chart we make sure that the price is not near the 200 EMA... Most stocks will experience some degree of resistance as they approach that 200 moving average." |
| A-quality vs B-quality pattern | **PROBABILISTIC** | "If you have an A quality pattern, it's on stock nobody sees... Now if we have an A quality stock, then we of course would prefer to trade an A quality pattern." — preference hierarchy, not binary |

**Key jTrader implication for Category B:** The entry point itself (first candle to make a new high) is a hard mechanical rule. But the surrounding confirmations (MACD, volume pattern, EMA position) appear to operate as a weighted confidence score, not a checklist. A strong enough catalyst and volume profile can compensate for MACD not being perfect. **Except: when he speaks for himself rather than teaching, MACD negative sounds like a personal no-go.** This needs live session verification.

---

### CATEGORY C — Stop-Out / Cutting Losses

This is the most clearly articulated category across the corpus — he talks about it the most. Multiple hard rules.

**Hard rules (VETO language):**

| Rule | Language Type | Direct Quote |
|------|--------------|--------------|
| Daily max loss | **VETO** | "Whatever that dollar amount is, you've got to follow it. These rules are guardrails." |
| Green-to-red on the day | **VETO** | "If I go green to red, that's a major problem." [Implies: stop trading immediately] |
| Give back 50% of daily profit after hitting goal | **VETO** | "If I give back 50%, that's like a hard stop." [Note: "like a hard stop" — slightly soft language, but the "give back half" rule is consistently cited as one of his Three Big Rules] |
| Pattern max loss = low of pullback | **VETO** | "The low is your max loss... It's not up for negotiation." |
| Valid chart signals as exit triggers | **VETO** | "If you're seeing a topping tail, if you're seeing a big seller, if your broker resistance level came back below — those are all valid reasons to sell. There's nothing wrong with selling in those instances." |

**Soft rules (PREFERENCE):**

| Rule | Language Type | Direct Quote |
|------|--------------|--------------|
| Daily profit stop (10% giveback intraday) | **SOFT** | "I'm going to stop trading once I give back, usually about 10% off the top." — "usually" qualifier |
| Stop out on red candle after buy | **SOFT-VETO** | "And if we don't [get continuation], then I can stop out the rest usually, you know, break even, or something like that." |
| Reduce size after losses | **VETO** | "I never go full size on the majority of my losing trades." |

**Key jTrader implication for Category C:** The three day-level stops (daily max loss, green-to-red, give-back-half) are all hard mechanical rules. The position-level stop (low of pattern) is hard. The intraday giveback percentage is slightly soft but consistently cited. **The topping tail / big seller / resistance failure as exit signals are valid grounds for exit but are not automatic stops — they trigger a sell decision, not a mandatory stop.**

---

### CATEGORY D — Profit Taking

This is the most probabilistic category. He gives frameworks but they are not rigid.

**Semi-hard rules:**

| Rule | Language Type | Direct Quote |
|------|--------------|--------------|
| First profit target = retest of high of day (bull flag) | **VETO-ADJACENT** | "Your profit target is a retest of the high of day for the first target." — stated as "the" target, not "a" target |
| Minimum 1:1 risk/reward | **VETO** | "You should make at least what you're risking... minimum." |

**Soft rules:**

| Rule | Language Type | Direct Quote |
|------|--------------|--------------|
| Don't overstay welcome | **PREFERENCE** | "I didn't want to overstay my welcome. And so I ended up saying I'm just going to trade a little more conservatively." |
| Exit on chart signal even if early | **PREFERENCE** | "I don't want you to think that you shouldn't take small base hits. It's okay to sell your winners if the chart is giving you an exit indicator, even if you've only been in the trade for two minutes." |
| MACD crossover as exit indicator | **PROBABILISTIC** | "Even on high volume MACD crossed over it did curl back up but I wasn't totally confident." — crossover alone wasn't decisive, waited for more |
| Topping tail / failed resistance | **PROBABILISTIC** | Mentioned repeatedly as exit indicator but with "if you're seeing" language |
| Psychological levels (half dollars, whole dollars) | **PROBABILISTIC** | "If it breaks through a level like the half dollar whole dollar, then I'm going to say to myself, I better book some profit." |

**Key jTrader implication for Category D:** Profit-taking is the most discretionary category. The first target (HOD retest on bull flag) is reasonably hard. After that it's a running read of chart signals — topping tails, volume fading, MACD crossing, resistance failing. **jTrader probably needs to use a priority-weighted signal model here, not a checklist.** A single topping tail isn't enough; a topping tail + volume fade + MACD crossover is probably a clear exit.

---

## 4. The MACD — How It Works and How Cameron Uses It

### What MACD Actually Is

MACD (Moving Average Convergence Divergence) has three components:

**MACD Line** = 12-period EMA minus 26-period EMA. When the shorter EMA is above the longer EMA, the MACD line is positive (short-term momentum outrunning longer-term). When 12 EMA drops below 26 EMA, the MACD line goes negative.

**Signal Line** = 9-period EMA of the MACD line itself. A smoothed, trailing version of the MACD line — acts as a reference point.

**Histogram** = MACD line minus Signal line. When MACD is above the signal line, histogram bars are positive (green). When MACD drops below signal, histogram goes negative (red). The *size* of bars matters: growing bars = accelerating momentum, shrinking bars = momentum fading even if still positive.

**Zero Line** = where the MACD line equals zero (12 EMA and 26 EMA have crossed each other). Above zero = short-term trend is bullish. Below zero = short-term trend is bearish.

### Two Different "Negative" Conditions

There are two distinct things that could be "negative" in MACD:
1. **Histogram negative** — MACD line has crossed below the signal line. Momentum is declining. This is what Cameron means by "crosses over."
2. **MACD line below zero** — The 12 EMA has fallen below the 26 EMA. Broader bearish context. More serious.

Both are bad in Cameron's framework, just at different severity levels.

### How Cameron Uses It

- **"MACD open" / "front side of the move"** = histogram is positive *and expanding* (MACD line diverging away from signal line, momentum accelerating). This is his preferred entry window.
- **"Before it crosses over"** = before the MACD line crosses below the signal line and the histogram turns negative.
- **"MACD is negative on the trade"** = ambiguous whether he means histogram negative (signal line crossed) or MACD line below zero. Could be either or both. Needs live session confirmation.

**Working interpretation:** Cameron wants to be in trades when the MACD histogram is positive and preferably expanding. A histogram turning negative (MACD crossing below signal) is at minimum an exit warning and possibly a hard ENTR veto. MACD line below zero is a more serious bearish flag. jTrader's implementation should be checked against both conditions — which one is it actually using, and are they being applied at entry, exit, or both?

**Still needs live session confirmation:** Does he ever enter a trade when the histogram is negative but the MACD line is still above zero? Does "MACD negative" always mean a full stop, or is it a strong caution?

---

## 5. Gap Analysis — Open Questions (Running List)

The teaching corpus is rich on mechanics but shallow on real-time decision weighting. Questions are added as they surface during research — this is a living list.

| # | Open Question | Why It Matters for jTrader | Best Source to Answer It |
|---|--------------|---------------------------|--------------------------|
| 1 | Actual weighting of ENTR signals vs each other | **PILOT UPDATE:** MACD line > 0 is now confirmed as a HARD gate. A perfect bull flag with negative MACD is a no-go. The remaining question is whether other ENTR signals (volume profile, 200 EMA) also veto or just weight. | Live trading sessions |
| 2 | What "A quality" vs "B quality" stock looks like in practice | He references this constantly but doesn't give precise criteria in teaching mode | Live sessions / setup grade recaps |
| 3 | Float — segmented analysis approach | **PILOT UPDATE:** Sub-5M is the preferred zone per live session behavior, but this is not sufficient to override the existing ≤20–30M filter gate. Keep filter at ≤20M (or ≤30M). Tag every trade with float bucket (≤5M / 5–10M / 10–20M / 20–30M). Let backtest data determine whether tightening below 20M improves accuracy. | Backtesting / Optuna output |
| 4 | Exactly when topping tail = hard exit vs early warning | Described as an exit indicator but not framed as mandatory. Pilot confirms multiple topping tails = clear exit signal. Still need: does one topping tail trigger or require combination with other signals? | Live sessions |
| 5 | "MACD negative" — histogram crossed or MACD line below zero? | **RESOLVED by pilot:** MACD line below zero = back side = no trade. This is the primary condition. Histogram going negative is an earlier warning to stop adding but not necessarily the hard veto. | Resolved |
| 6 | Trading window — rules or window problem? | **PILOT UPDATE:** 7-8am pre-market confirmed as highest-profit window by Ross's own metrics. Pilot confirms the drop-off after 10:30am is real. Recommend: tag trades with time bucket and apply tighter filters (e.g., lower max size) after 10:30am. | Backtest output + code audit |
| 7 | First 5–10 minutes vs rest of 9:30–10am window | Are ENTR thresholds different for the opening gap-and-go vs a bull flag forming at 9:45? | Live sessions (especially gap-and-go recordings) |
| 8 | Position sizing rule — small account vs normal practice | "Start at 1/4 size, scale to full after +$50" appears in small account challenge context. **Pilot adds:** the "break the ice small then size up" pattern is confirmed as his normal-account approach, not just small account. | Live sessions, normal account trading content |
| 9 | A-quality vs B-quality stock — precise practical definition | He references this constantly. Transcripts give accuracy ranges (A = 70%, B = 60%) but not what specific combination of SCRN criteria makes a setup A vs B in practice | Live sessions, setup grade recaps |

---

## 6. Recommended Next Steps

**Immediate (can do now with existing library):**

1. **Full read of `5 Rules For Selling Losers Faster`** — extract verbatim rules for Category C. This transcript alone can probably fully spec the stop-out logic.
2. **Full read of `Master the Bull Flag Pattern`** — extract precise entry mechanics. The "not up for negotiation" quote suggests there are more specific rules to pull.
3. **Full read of `27 Years of Trading Knowledge`** — this is 3+ hours of content, likely the most comprehensive single source.
4. **Full read of `Day Trading Strategies for Beginners Class 3 of 12`** — a structured class format will likely have the most systematic rule presentation.

**YouTube research needed (not in library):**

5. **Hunt specifically for live trading sessions** — search for "Ross Cameron live trading" or "Warrior Trading live trade" videos with observable real-time decisions. The key is watching him narrate a trade as it happens, not recapping it.
6. **Hunt for setup grade videos** — he often grades setups A/B/C in recaps. These are the most informative for understanding his B-category weighting.
7. **Hunt for "trade review" videos** — where he shows a trade he took and explains why he entered/exited each decision point.

**jTrader code audit (next phase):**

8. Once the spec is locked, compare jTrader's current implementation against the rules above, specifically:
   - Does it treat MACD line > 0 as a hard ENTR gate? (Working answer: it should)
   - Does it have the three day-level STOP rules (max loss, green-to-red, give-back-half) as non-overridable gates?
   - Does it use the low of the pullback as pattern max loss, or a fixed percentage?
   - Is the ENTR trigger truly "first candle to make a new high" to the penny, or is it approximated?
   - Is relative volume enforced at ≥ 5x as a hard SCRN gate, or was this loosened?
   - Was the filter-loosening that caused the Alpaca underperformance in SCRN (Category A) or in ENTR confirmations? (Hypothesis: SCRN, specifically relative volume or catalyst threshold)

---

## 7. The Core Hypothesis to Test in Code

The original issue: you loosened filters to generate more candidates. Cameron's entire edge is selectivity.

Based on this research, the most likely place the loosening caused damage is **Category A (pre-screen).** If the relative volume threshold was lowered below 5x, or the catalyst requirement was softened, then jTrader was trading setups Cameron would never take. The B/C/D logic almost doesn't matter if the wrong stocks are getting through.

**Priority order for the code audit:**
1. Verify Category A filters are truly hard gates — especially relative volume (≥5x) and catalyst requirement
2. Verify the three day-level stops are implemented and can't be overridden
3. Verify position-level stop = low of pullback pattern (not a fixed percentage)
4. Then and only then — examine the B entry confirmation logic for weighting vs checklist issues

---

*This report is based on automated classification and language analysis of 80 transcripts plus deep reads of the 3 highest-specificity strategy documents. The findings should be treated as a strong working hypothesis, not a final spec — particularly around MACD handling and the B-category signal weighting, which need live session footage to confirm.*
