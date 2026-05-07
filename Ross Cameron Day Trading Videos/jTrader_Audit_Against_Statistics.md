# jTrader Audit Against RC Statistics
### Mapping Current jTrader Rules vs. 1,787-Session Statistical Baseline

**Date:** 2026-05-05
**Auditor:** Claude Sonnet 4.6 (Phase 2 session)
**Sources:**
- `RC_STRATEGY_STATISTICS.md` — 1,787 sessions, 5,261 trades (the numbers)
- `Older/RC_Strategy_Research_Report.md` — 43 rules + 9 pilot findings (the spec)
- `production/trading/entry_engine.py` — Gate 1-5 implementation
- `production/trading/exit_engine.py` — 11-step exit cascade
- `production/trading/models.py` — ScannerConfig / EntryConfig / ExitConfig defaults
- `production/trading/portfolio_manager.py` — Daily risk rule observer
- `production/simulator/simulation_engine.py` — PositionManager (sizing)

---

## Executive Summary

jTrader has a **solid mechanical skeleton** for entry gate sequencing and exit cascades. The critical gaps are:

1. **Market temperature is completely absent** — cold markets are net-losing (-$63/trade avg, 53.9% win rate) and jTrader has no gate or position-size adjustment for this condition
2. **News catalyst is disabled** — Pillar 5 is TODO; data shows +12.7pp win rate advantage with news (73.4% vs 60.7%)
3. **Daily risk rules observe-only** — PortfolioManager logs when rules would fire but never enforces them; max-loss-hit sessions show 30.9% win rate and -$4,454/trade avg
4. **Float filter is disabled** — one of the hardest pre-screen gates is toggled off
5. **MACD entry gate is disabled** — `enable_macd = False` by default, contradicting the confirmed VETO finding
6. **Behavioral deviation detection is completely absent** — sessions with deviation: 49.2% win rate vs 73.1% without; biggest statistical argument for the algorithm
7. **Oversizing protection has a logic bug** — `max_position_pct=1.5` in the old PositionManager (simulator uses 20% correctly, but old code still exists)

---

## Rule-by-Rule Audit Table

| # | Rule | Category | jTrader Status | Statistical Validation | Recommendation |
|---|------|----------|----------------|------------------------|----------------|
| 1 | Price range $1–$20 | SCRN (A) | ✅ Implemented — `min_price=1.0, max_price=20.0`, enabled by default | Strong preference confirmed. Below $1 = too volatile, above $20 = too expensive for small accounts. | Keep. Validated by strategy. |
| 2 | Up ≥10% from prior close | SCRN (A) | ✅ Implemented — `min_premarket_gain=10.0`, enabled | Gap-and-go 78.2% win rate (+$3,791 avg) — top setup. Validates pre-market gain as core screen. | Keep. May want to test 15%+ threshold. |
| 3 | Relative volume ≥5x | SCRN (A) | ✅ Implemented — `min_relative_volume=5.0`, enabled | Gap-scanner 69.3% win rate; premarket-scan 70.2%. High-volume sessions outperform. | Keep. This is a HARD VETO per RC. Do not lower below 5x. |
| 4 | Float ≤20M shares | SCRN (A) | ❌ **DISABLED** — `enable_float_filter=False` (comment: "see distribution query") | Sub-5M float = maximum squeeze per pilot finding. Float quality directly affects squeeze dynamics. | **Enable.** Set at ≤20M initially (matches strategy), track by float bucket to validate tighter cutoff. |
| 5 | Market cap ≤$500M | SCRN (A) | ❌ Disabled — `enable_market_cap_filter=False` | Indirect — low float stocks with high market cap are typically shares-outstanding rich, not true small caps. | Enable cautiously. Let backtest confirm. |
| 6 | News catalyst (Pillar 5) | SCRN (A) | ❌ **NOT IMPLEMENTED** — `data['news_check'] = 'SKIPPED'` (literal TODO in code) | **73.4% win rate WITH news** vs 60.7% without — **+12.7pp advantage**. Total P&L with news: $6.45M vs $3.07M without on fewer trades. | **CRITICAL GAP.** Integrate news_fetcher into Pillar 5. Even a binary news/no-news flag would add +12.7pp edge. |
| 7 | Trading window 9:30–11:00am | ENTR (B) | ✅ Implemented — hard window gate, `TRADING_END_HOUR = 11` | 9:30–10:30am confirmed as primary window. Drop-off after 10:30am confirmed by pilot sessions. | Keep. Consider tightening to 10:30am with reduced size window 10:30–11:00am. |
| 8 | MACD line > 0 (front-side gate) | ENTR (B) | ❌ **DISABLED** — `enable_macd=False` in EntryConfig defaults | **CONFIRMED HARD VETO** per pilot batch. "MACD line below zero = back side = no trade." Current code checks HISTOGRAM, not MACD line. Even if enabled, it's the wrong signal. | **CRITICAL GAP.** (a) Enable MACD gate. (b) Switch from histogram check to MACD LINE > 0 check (12 EMA - 26 EMA > 0). |
| 9 | EMA-9 above price (entry) | ENTR (B) | ❌ Disabled — `enable_ema9=False` in EntryConfig defaults | Consistent with trend-following. EMA-9 cross used on EXIT (correctly) — entry side should gate too. | Enable. Price > EMA-9 = stock trending up, aligned with front-side logic. |
| 10 | Uptrend required | ENTR (B) | ✅ Implemented — `enable_trend=True` (`is_trending_up()`) | Aligned with front-side / gap-and-go framework. | Keep. |
| 11 | Volume on up-bars dominates | ENTR (B) | ✅ Implemented — `volume_on_up_bars_dominates()` in Gate 3 | Confirmed: "High volume on green candles, light volume on red candles" = authentic buying sentiment. | Keep. |
| 12 | Buying volume gate | ENTR (B) | ❌ Disabled — `enable_buying_volume=False` | Selling pressure at entry = danger signal. Validates caution. | Consider enabling, but tune threshold carefully — may be redundant with volume direction check. |
| 13 | Pattern: Bull Flag | ENTR (B) | ❌ **DISABLED** — `enable_bull_flag=False` (Trial 193 result) | Bull-flag/flat-top: 69.6% win rate, +$2,134 avg (56 trades). Micro-pullback: 74.3%, +$3,560. | Review whether disabling bull flag improved or hurt. Statistics suggest bull flag is better than ABCD (42.9%) but slightly below micro-pullback. May be worth re-enabling. |
| 14 | Pattern: Micro Pullback | ENTR (B) | ✅ Implemented — `enable_micro_pullback=True` | 74.3% win rate, +$3,560 avg — second-best setup. Validated. | Keep. |
| 15 | Pattern: Dip Buy | ENTR (B) | ✅ Implemented — `enable_dip_buy=True` | Maps to pullback/dip category: 64.0% win rate, +$1,728 avg. Lower than micro-pullback but positive. | Keep with current thresholds. May tighten. |
| 16 | Pattern: Flat Top Breakout | ENTR (B) | ✅ Implemented — `enable_flat_top=True` | Maps to breakout category: 56.4% win rate, +$1,093 avg. **Lowest win rate among enabled patterns.** | Watch. Statistics suggest flat-top/breakout is jTrader's weakest enabled setup. Consider raising threshold or adding MACD gate specifically here. |
| 17 | Pattern: ABCD | ENTR (B) | ❌ Disabled — `enable_abcd=False` (Trial 193) | ABCD: **42.9% win rate** (14 trades in data) — net-losing by win rate. Trial 193 was correct to disable. | Keep disabled. Data confirms poor performance. |
| 18 | Pattern: Gap-and-Go | ENTR (B) | ⚠️ **Missing as explicit pattern** | **78.2% win rate, +$3,791 avg** — top setup by frequency + performance (404 trades). | **SIGNIFICANT GAP.** Gap-and-go is the #1 setup by RC and statistics. jTrader has no dedicated gap-and-go detector. Micro-pullback may partially catch it, but an explicit gap-and-go pattern with breakout-of-premarket-high trigger should be implemented. |
| 19 | Pattern: VWAP break/curl | ENTR (B) | ⚠️ **Missing as explicit pattern** | **78.1% win rate, +$7,126 avg** — highest avg result of ANY setup. | **HIGH VALUE GAP.** 137 trades in dataset, 78% win rate. Implement VWAP reclaim/curl entry trigger. |
| 20 | Pattern: Halt-Resume | ENTR (B) | ⚠️ **Missing as explicit pattern** | 68.0% win rate, +$654 avg (428 trades). Moderate performance but very high frequency. | Nice-to-have. Lower avg result than gap-and-go/VWAP. Implement after higher-priority gaps. |
| 21 | Risk/Reward ≥ 2:1 | ENTR (B) | ✅ Implemented — `min_rr_ratio=2.0`, `enable_rr=True` | "Minimum 1:1 risk/reward" per RC = strategy floor. jTrader's 2:1 minimum is stricter (better). | Keep. |
| 22 | Stop = low of pattern | STOP (C) | ✅ Implemented — pattern-specific stop in each detector + `stop_buffer=0.076` | "The low is your max loss — it's not up for negotiation." Validated as hard rule. | Keep. Stop buffer tuning is appropriate. |
| 23 | Hard stop: price hits stop | STOP (C) | ✅ Implemented — Gate 1 in exit cascade, unconditional | Core mechanics. | Keep. |
| 24 | Daily max loss rule | STOP (C) | ⚠️ **OBSERVE-ONLY** — PortfolioManager logs but never enforces | **30.9% win rate after max-loss-hit, -$4,454 avg**. After hitting max loss, continuing trading is catastrophic. | **CRITICAL GAP.** Must enforce. PortfolioManager must halt new entries when `DAILY_MAX_LOSS` fires. |
| 25 | Green-to-red rule | STOP (C) | ⚠️ **OBSERVE-ONLY** — same as above | Going green-to-red = emotional trading spiral begins. Highly correlated with behavioral deviation sessions. | **Enforce.** Halt new entries when `GREEN_TO_RED` fires. |
| 26 | Give-back-half rule | STOP (C) | ⚠️ **OBSERVE-ONLY** — same as above | "If I give back 50%, that's a hard stop." Protects against givebacks on strong green days. | **Enforce.** Halt new entries when `GIVE_BACK_HALF` fires. |
| 27 | EMA-9 cross exit | STOP (C) | ✅ Implemented — Gate 5 in exit cascade, `ema_cross_qty_pct=0.25` | Aligned with "close below EMA while profitable = trend reversed." | Keep. Only fires in profit — correct. |
| 28 | MACD flip exit | STOP (C) | ⚠️ Disabled — `enable_macd_flip_exit=False` | "Before it crosses over" — histogram crossover = momentum reversing. | Enable. When MACD histogram flips negative while profitable, that's the exit signal RC describes. |
| 29 | Trailing stop | STOP (C) | ✅ Implemented — activates after T1, 26.2-cent trail (Trial 193) | Aligned with "don't overstay welcome" and locking gains. | Keep. |
| 30 | Selling pressure exit | STOP (C) | ❌ Disabled — `enable_selling_pressure=False` (comment: "fires too early") | Selling pressure is a valid signal but poorly calibrated if it's firing too early. | Keep disabled until threshold is tuned. The 2x ratio (selling > 2× buying) should be re-evaluated. |
| 31 | Resistance / prior-day-high exit | STOP (C) | ❌ Disabled — `enable_resistance_exit=False` | "Stock will experience resistance approaching 200 EMA / prior-day high." | Enable Phase 3 features when ready. Not critical now. |
| 32 | Target 1 (scale out) | PROF (D) | ✅ Implemented — T1 at 2.19× risk (Trial 193), scale 30% | "Profit target = retest of high of day for first target." Validated. | Keep. |
| 33 | Target 2 (scale out) | PROF (D) | ✅ Implemented — T2 at 3.0× risk, scale 25% | Consistent with "don't overstay welcome" and progressive profit-taking. | Keep. |
| 34 | Time decay exit (11am dead zone) | PROF (D) | ✅ Implemented — `time_decay_hour=12` (exit profitable positions after noon) | 11am–2pm = dead zone per RC. Exit at noon is slightly late vs the strategy spec. | Consider tightening to 11am or adding a smaller size / raise-stop rule at 11am. |
| 35 | Market temperature gate | SCRN (A) | ❌ **COMPLETELY ABSENT** | **Cold market: 53.9% win rate, -$63/trade (net-losing over 1,556 trades)**. Hot market: 71.9%, +$3,516. Difference is massive. | **CRITICAL GAP.** Implement market temperature assessment. Cold = reduce size by 50%+ or stop entirely. |
| 36 | Oversizing protection | SCRN (A) | ⚠️ Partial / Bug | **Oversized: 49.7% win rate, -$176/trade (net-losing over 743 trades)**. SimulationRunner uses `max_position_pct=20` (correct). Old PositionManager still defaults to `max_position_pct=1.5` (wrong). | Confirm SimulationRunner's 20% cap is used everywhere. Audit that old PositionManager with 1.5% cap isn't reachable in live path. |
| 37 | Position sizing: cold market reduction | SCRN (A) | ❌ Absent | RC: "when it's cold, reduce max share size by 50-75%." Validated by -$63/trade cold average. | Implement as part of market temperature gate. |
| 38 | Front-side/back-side framework | ENTR (B) | ⚠️ Partial — trend gate present, MACD gate disabled | Front-side = MACD line > 0 + new highs. Back-side = MACD < 0 + failing to break prior high. MACD LINE check is the key missing piece. | Fix by enabling and correcting MACD gate (rule #8). |
| 39 | Behavioral deviation detection | META | ❌ **COMPLETELY ABSENT** | **49.2% win rate WITH deviation vs 73.1% without** — the single biggest argument for automating this. Most common deviations: FOMO entry (74), oversize (56), overtrading (38), revenge trade (29). | The algorithm itself is the behavioral deviation prevention system. Enforce rules #24-26 (daily stops) and the MACD gate to structurally prevent the most common deviations. |
| 40 | Max trade count per day | META | ❌ Not implemented | Overtrading (38 sessions with deviation) is the 3rd most common behavioral error. No gate exists. | Add max_trades_per_day limit (e.g. 3-5). Optuna can tune it. |
| 41 | Sector theme detection | SCRN (A) | ❌ Not implemented | Pilot finding: sector theme amplifies catalyst quality. Data shows pharma 71.0%, tech 71.9% — slightly better than general. | Low priority. News catalyst (rule #6) partially captures this. Sector filter can come later. |
| 42 | Order spoofing detection (L2) | ENTR (B) | ❌ Not implemented | Pilot finding: spoofed walls = squeeze fuel. Niche, requires L2 feed. | Very low priority. Skip until L2 data is available. |
| 43 | "Obvious trade" standard | SCRN (A) | ⚠️ Partial — relative volume and gain % provide partial ranking | RC: only trade when the setup is unambiguously the top candidate. A composite "obviousness score" (rel-vol rank, gain% rank, news quality) would implement this. | Consider adding multi-symbol ranking step: only enter if this symbol is the top-ranked across all current candidates. |

---

## Specific Answers to the Brief's Questions

### Q1: Which of the 43 known rules are already in jTrader?

**Fully implemented (13 rules):**
- Price range $1–$20
- Up ≥10% from prior close (premarket gain)
- Relative volume ≥5x (hard gate)
- Trading window 9:30–11:00am
- Uptrend required
- Volume on up-bars dominates
- Pattern: Micro Pullback ✅
- Pattern: Dip Buy ✅
- Pattern: Flat Top Breakout ✅
- Risk/Reward ≥2:1
- Stop = low of pattern + buffer
- Hard stop (price hits stop)
- Trailing stop (post-T1)
- Target 1 + Target 2 scale-outs
- Time decay exit (noon)

**Partially implemented (4 rules):**
- Front-side framework (trend gate works; MACD gate disabled and wrong signal)
- EMA-9 exit (exit side correct; entry gate disabled)
- MACD flip exit (coded but disabled)
- Oversizing protection (simulator OK; old PositionManager class has 1.5% cap bug)

**Observe-only / not enforced (3 rules):**
- Daily max loss stop → OBSERVE ONLY
- Green-to-red stop → OBSERVE ONLY
- Give-back-half stop → OBSERVE ONLY

**Missing entirely (23 rules):**
- News catalyst (Pillar 5)
- Float filter (disabled)
- Market temperature gate (cold/hot)
- Position sizing adjustment for cold markets
- MACD line > 0 (correct signal type — currently uses histogram)
- EMA-9 entry gate
- Gap-and-go pattern detector
- VWAP break/curl pattern detector
- Halt-resume pattern detector
- Behavioral deviation detection system
- Max trades per day
- Sector theme detection
- Order spoofing detection

---

### Q2: Does jTrader implement oversizing protection?

**Partial.** `SimulationRunner` uses `max_position_pct=20` (20% of account per trade), which is reasonable. But the older `PositionManager` class defaults to `max_position_pct=1.5` — this 1.5% cap is too conservative (positions would be tiny). The key risk: if any code path still instantiates the old `PositionManager` with the 1.5% default, position sizes are wrong.

**Statistical context:** Oversized = 49.7% win rate, **-$176/trade average** (743 trades, net losing). The data is unambiguous — oversizing destroys edge.

---

### Q3: Does jTrader gate trades based on market temperature?

**No.** There is no market temperature variable, cold/hot classifier, or position-size scaling based on market conditions anywhere in the codebase.

**Statistical context:** Cold market = **53.9% win rate, -$63/trade** (1,556 trades, net losing). This is not a minor adjustment — cold markets are literally net negative. The simplest implementation would be a morning assessment flag (from scanner data: leading gapper %, volume quality, news presence) that either blocks trading or halves position size.

---

### Q4: Does jTrader enforce behavioral deviation detection?

**No.** The algorithm has no concept of behavioral deviation, and more critically, the three daily risk rules that would prevent the most common deviations (FOMO entry after a loss, overtrading, revenge trading) are observe-only in PortfolioManager and never halt new entries.

**Statistical context:** With behavioral deviation = **49.2% win rate, +$43/trade**. Without = **73.1% win rate, +$2,905/trade**. The algorithm's primary advantage over Ross Cameron trading himself is that it *cannot* behaviorally deviate — but only if the daily stops are actually enforced.

**Most common deviations (by count):**
1. FOMO entry (74) — prevented by: enforcing daily max loss / green-to-red stops, strict entry gate discipline
2. Oversize (56) — prevented by: `max_position_pct` cap
3. Overtrading (38) — prevented by: max trades/day limit
4. Revenge trade (29) — prevented by: enforcing daily stops after a loss

---

### Q5: Does jTrader enforce max loss stops?

**No.** `PortfolioManager` detects when `DAILY_MAX_LOSS` would fire but returns events without any mechanism to halt new entries. The simulation and live scanner continue trading regardless.

**Statistical context:** Max loss hit sessions = **30.9% win rate, -$4,454/trade average** (414 trades). Normal sessions = 68.0% win rate, +$2,479/trade. Continuing to trade after hitting max loss is the single most destructive behavior in the entire dataset.

---

## Priority-Ordered Recommendations

### Tier 1 — Critical (implement before live trading)

| Action | Why |
|--------|-----|
| **Enforce daily risk rules** (daily max loss, green-to-red, give-back-half) | 30.9% win rate after max loss hit. PortfolioManager detects but never halts. Wire `any_rule_fired()` to block new entries in live scanner and simulator. |
| **Implement news catalyst gate (Pillar 5)** | +12.7pp win rate advantage (73.4% vs 60.7%). Currently TODO/SKIPPED. Even binary flag matters. |
| **Fix MACD gate: use MACD LINE > 0, not histogram** | Confirmed HARD VETO per pilot. Current code checks histogram sign (wrong signal). Switch to: (12 EMA - 26 EMA) > 0. |
| **Enable MACD gate** | `enable_macd=False` in defaults. Once fixed to check MACD line, enable it. |
| **Enable float filter** | Currently disabled with "see distribution query" comment. Pillar 4 is a hard SCRN gate. Enable at ≤20M. |

### Tier 2 — High Priority (implement in next sprint)

| Action | Why |
|--------|-----|
| **Implement market temperature assessment** | Cold = net-losing (-$63/trade). Even a simple "is leading gapper ≥30%?" morning check would gate bad days. |
| **Add gap-and-go pattern detector** | 78.2% win rate, +$3,791 avg — top setup. Currently missing. Entry = break of premarket high on first 1-min candle to new high. |
| **Add VWAP break/curl pattern detector** | 78.1% win rate, +$7,126 avg — highest avg result of any setup. 137 trades in dataset. |
| **Enable EMA-9 entry gate** | Price > EMA-9 = trend confirmation. Currently disabled. |
| **Enable MACD flip exit** | Histogram crossing negative while profitable = momentum reversal signal. Currently coded but disabled. |
| **Add max trades per day limit** | Overtrading is 3rd most common deviation. Simple count gate prevents it. |

### Tier 3 — Medium Priority (optimize)

| Action | Why |
|--------|-----|
| **Re-evaluate bull flag** | Disabled by Trial 193. 69.6% win rate in data — not bad. Worth testing against micro-pullback. |
| **Implement cold-market position size reduction** | Even if market temp gate isn't built, halving size when conditions are poor reduces damage. |
| **Tighten time decay to 11am** | RC strategy: 11am = dead zone. jTrader currently exits at noon. 60 minutes of suboptimal trading. |
| **Raise flat-top bar** | Breakout category = 56.4% win rate — weakest enabled setup. Raise MACD or volume requirements for this pattern specifically. |
| **Audit old PositionManager path** | Confirm `max_position_pct=1.5` class is not reachable in live trading path. |

---

## Open Questions from This Audit

1. **Is `PositionManager` (old, 1.5% cap) reachable from any live trading path?** The `SimulationRunner` uses 20%, but the old class still exists. Need code trace.

2. **What does Trial 193 show for bull flag specifically?** It was disabled but the data shows 69.6% win rate. Was it underperforming micro-pullback specifically in backtests, or was it adding noise?

3. **What is "MACD open" vs just MACD line > 0?** RC's language "MACD open" sometimes sounds like expanding histogram (momentum accelerating), not just line above zero. Need to confirm: is the entry gate MACD line > 0, or specifically MACD histogram positive AND expanding?

4. **How to implement market temperature without live scanner data during backtesting?** The statistics are clear (cold = net-losing), but the classifier needs to be definable from historical data. Leading gapper % and volume quality are candidates.

5. **Gap-and-go exact entry mechanics**: RC says "first candle to make a new high — that is the moment of entry, that is to the penny." For a gap-and-go, this means break of the premarket high on the first 1-minute candle. Need to verify our bar history contains premarket highs to detect this correctly.

---

## Contradictions Between jTrader and the Data

| Contradiction | jTrader | Statistics | Verdict |
|---|---|---|---|
| ABCD disabled | `enable_abcd=False` | 42.9% win rate — net-losing pattern | ✅ Correct to disable |
| Bull flag disabled | `enable_bull_flag=False` | 69.6% win rate, +$2,134 avg | ⚠️ May be worth revisiting |
| Time decay at noon | Exits at noon | Dead zone starts at 11am per RC | ❌ Exit should move earlier |
| MACD histogram check | Checks histogram sign | MACD LINE > 0 is the hard gate, not histogram | ❌ Wrong signal being checked |
| Daily stops observe-only | PortfolioManager logs only | Max-loss sessions: 30.9% win rate | ❌ Must enforce, not observe |
| No market temperature | No cold/hot detection | Cold market: net-losing (-$63/trade) | ❌ Critical missing gate |

---

*Generated from full read of production codebase + statistical baseline. Re-run analysis after implementing Tier 1 recommendations.*
