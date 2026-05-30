# jTrader Implementation Guide
# Based on Optuna 500-trial run + Full Corpus Research

**Generated:** 2026-05-26  
**Source:** 292 complete Optuna trials (study `trading_2025-01-10_2025-09-30`) + concept corpus (1,799 sessions)  
**Best trial:** #294, objective = +$14,166 over 181 trading days (Jan–Sep 2025)

---

## ⚠️ CODE FREEZE — DO NOT IMPLEMENT UNTIL OPTUNA RUN COMPLETES

**Status:** Optuna run `trading_2025-01-10_2025-09-30` is IN PROGRESS (~350/500 trials, ETA ~3h as of 2026-05-26 11:36 AM).

**Do NOT touch these files until 500 trials complete:**
- `production/trading/entry_engine.py`
- `production/trading/exit_engine.py`
- `production/simulator/simulation_engine.py`
- `production/trading/models.py`
- `research/optimizer/run_config.py`
- `research/optimizer/optuna_run.py`
- `research/optimizer/simulate_one.py`

**Why:** Changing any simulation or model file mid-run makes trials 350-500 incomparable to trials 0-349. The objective values become apples-to-oranges — TPE will sample from mixed data and find garbage. The entire run is wasted.

**When run completes:**
1. Verify 500 complete trials in DB
2. Re-run `optuna.importance.get_param_importances()` on all 500 trials
3. Run out-of-sample validation Oct 2025 – Mar 2026 with best config
4. THEN implement changes from this guide

**Safe to do now (don't affect simulation):**
- Docs, README, concept pages
- Frontend / backend app changes
- Data collection scripts
- This guide

---

## Critical Update: Strategy Regime Has Shifted

The earlier importance analysis (291 trials) found `a_enable_premarket_gain=False` dominant. Trials 294-348 have since found a **completely different, higher-performing regime**. ALL top-10 trials now agree on the opposite configuration.

**Old best config (trials 0-290):** gap-and-go only, no filters, no MACD  
**New best config (trials 294-348):** MACD-confirmed + premarket gain required + multi-pattern

Do not implement the old regime. Use the new findings below.

---

## Section 1: Toggle Flags (Binary Params)

### Always ON — top 10 unanimous

| Flag | Default | New Value | Corpus Evidence |
|---|---|---|---|
| `a_enable_premarket_gain` | True | **True** | Screening for premarket movers improves signal quality; momentum already confirmed |
| `b_enable_macd` | varies | **True** | MACD LINE > 0 = front-side filter (see §3 for bug fix) |
| `b_enable_micro_pullback` | True | **True** | 74.3% win rate, 350 trades; confirmed Tier 1 trigger |
| `b_enable_abcd` | varies | **True** | Low raw win rate (42.9%) but scoring threshold (§5) filters bad setups |
| `b_enable_dip_buy` | True | **True** | 64.0% win rate, 944 trades; highest volume pattern |
| `b_enable_trend` | varies | **True** | Front-side confirmation complements MACD gate |
| `a_enable_premarket_gain` | True | **True** | Hot movers pre-screened; combines well with MACD entry gate |
| `c_enable_macd_flip_exit` | False | **True** | Valid exit signal: MACD histogram flip → momentum reversing → scale out |

### Always OFF — top 10 unanimous

| Flag | Default | Why Disabled | Corpus Evidence |
|---|---|---|---|
| `b_enable_bull_flag` | varies | **False** | Underperforms vs other patterns in this param regime |
| `b_enable_ema9` | varies | **False** | EMA9 adds noise; MACD (which incorporates EMA12/26) is sufficient |
| `b_enable_vwap_break_curl` | varies | **False** | VWAP break/curl has highest EV ($5,565) but anticipatory entry style conflicts with MACD gate |
| `b_enable_abcd` (note) | — | See above | Enabled but only fires on high-confidence setups per scoring threshold |

### Mixed (majority signal)

| Flag | Top-10 Split | Recommendation |
|---|---|---|
| `b_enable_flat_top` | 8/10 True, 2/10 False | **True** (69.6% win rate, well-anchored trigger) |

---

## Section 2: Exit Parameters — Critical Values

### T1 Target (c_target1_ratio)

| Metric | Old default | New optimized |
|---|---|---|
| `target1_ratio` | 2.19 | **1.16–1.34 (avg ≈ 1.28)** |
| `target1_qty_pct` | 0.30 | **0.44–0.46 (avg ≈ 0.45)** |

**What this means:**
- T1 is at entry_price + (stop_distance × 1.28)
- At T1, sell ~45% of position
- Example: entry $5.00, stop $4.90 ($0.10 risk), T1 = $5.00 + $0.128 = $5.128
- Risk:Reward at T1 = 1:1.28 (barely positive, takes profits EARLY)

**Why this works (corpus evidence):** Gap-and-go concept page shows 38% of trades are pure scalps <5 min. Micro-pullback and dip-buy patterns typically have tight targets. Taking 45% off early reduces risk while keeping exposure for the T2 run.

**T2 Target:** `target2_ratio` = 4.21 in best trial. After T1 hit and stop moved to breakeven, the remaining 55% rides to 4.21x stop distance. High upside for runners.

### Selling Pressure Exit

| Param | Default | Optimized |
|---|---|---|
| `enable_selling_pressure` | False | **True** |
| `selling_pressure_ratio` | 2.0 | **2.46–2.55 (avg ≈ 2.5)** |
| `selling_pressure_qty_pct` | 0.50 | **0.90–0.91 (avg ≈ 0.91)** |

**Code (current implementation is correct, just wrong defaults):**
```python
# exit_engine.py — already implemented, update defaults in models.py:
if selling_vol > buying_vol * cfg.selling_pressure_ratio:  # ratio = 2.5
    qty = max(1, int(shares_remaining * cfg.selling_pressure_qty_pct))  # qty_pct = 0.91
    return ExitSignal(reason='SELLING_PRESSURE', price=price, qty=qty)
```

**Why 2.5x ratio (not 2.0x):** At 2.0x, fires on normal volatility during consolidation. At 2.5x, only fires on real liquidation pressure. Corpus: Ross scales out on "tape flips from buying to selling" (not on every dip).

**Why 91% (not 50%):** When selling pressure is real (2.5x confirmed), exit nearly the full position. Keeping 9% is a hedge if it recovers. The old 50% left too much exposure on genuine reversals.

### Time Decay

| Param | Default | Optimized |
|---|---|---|
| `time_decay_hour` | 10 (10:30) | **11.0–12.0** |

All top-10 trials use `c_time_decay_hour = 11.0` (8 of 10) or `12.0` (2 of 10, both very hot day configs). This is later than the default 10:30, meaning:
- Positions held through 11 AM on normal days
- `c_time_decay_hour = 12` in best trial (hot-day oriented configs)

**Corpus (gap_and_go.md, time_of_day.md):** "After 10:30am — morning momentum has decayed" for COLD days. Hot days: trade until noon+. The optimizer found 11:00 as the sweet spot (most days aren't cold).

---

## Section 3: MACD Bug Fix Required

The MACD entry gate is now ENABLED in all top configs. **There is a known bug in entry_engine.py:**

**Current (WRONG):**
```python
# Checks histogram, not MACD line
if ecfg.enable_macd and indicators['macd_histogram'] <= 0:
    return None
```

**Correct implementation:**
```python
# Must check MACD LINE (12 EMA − 26 EMA), not histogram
macd_line = indicators.get('macd_line')  # 12 EMA - 26 EMA
if ecfg.enable_macd and macd_line is not None and macd_line <= 0:
    return None
```

**Also required:** `calculate_macd()` in `indicators.py` must return `'macd_line'` key (12 EMA - 26 EMA), not just the histogram. Verify this key exists.

**Pattern-specific rule (corpus-backed):**
- Gap-and-go: MACD relevance = 3.7% (not used, first 26 bars have no data)
- VWAP-reclaim: MACD relevance = 2.6% (skip gate)
- Dip-buy: MACD relevance = 4.4% (already enforced inside detect_dip_buy)
- Micro-pullback: MACD relevance = 4.7% (front-side baked into pattern structure)

**Implementation:** After bug fix, make the gate pattern-aware — skip for GAP_AND_GO and VWAP_RECLAIM, apply for others.

---

## Section 4: Add-On Mechanics

| Param | Default | Optimized |
|---|---|---|
| `add_pct_tier1` | 0.25 | **0.30** |
| `add_pct_tier2` | 0.25 | **0.28** |
| `max_add_ons` | varies | **3** |
| `e_time_cutoff_minute` | varies | **19** (9:49 AM — no adds after) |
| `e_enable_micro_pb_add` | varies | **False** |
| `e_enable_new_high` | varies | **True** |
| `e_enable_vwap_retest` | varies | **True** |
| `e_enable_whole_dollar_add` | varies | **True** |
| `e_hot_market_multiplier` | 1.0 | **1.26** |

**Tier sizing interpretation:**
- Initial position: 100%
- Add 1 (tier1): 30% of initial
- Add 2 (tier2): 28% of initial
- Add 3 (tier3): default ~20% (not in top params, use default)
- Total 3 adds: initial + 30% + 28% + 20% = 178% maximum

**Add trigger priority (enabled):**
1. `e_enable_new_high = True` — add when stock makes new high (front-side confirmation)
2. `e_enable_vwap_retest = True` — add on VWAP retest that holds (dip to support)
3. `e_enable_whole_dollar_add = True` — add on break of whole-dollar level

**Add cutoff at 9:49 AM** (19 minutes from open): Corpus shows <2% of adds occur after 10:30; the optimizer found even tighter at 9:49. Add-ons are a first-30-minutes mechanic.

**Hot market multiplier 1.26x:** On hot days, add-on sizes are 26% larger. Corpus: "Ross sizes INTO strength" and on front-side hot days increases add size.

---

## Section 5: Scoring Thresholds (Temperature-Based)

| Param | Default | Optimized |
|---|---|---|
| `f_threshold_hot` | varies | **25–27 (very low)** |
| `f_threshold_neutral` | varies | **56** (best trial) |
| `f_threshold_cold` | 70 | **75–78 (avg ≈ 77)** |
| `f_threshold_chop` | varies | **66** (best trial) |
| `f_size_hot` | 1.0 | **1.47–1.50 (avg ≈ 1.49)** |
| `f_size_neutral` | 0.75 | **0.75** (unchanged) |
| `f_size_cold` | varies | **0.39** (best trial) |
| `f_size_chop` | 0.25 | **0.46–0.47** |

**Strategy interpretation:**

**HOT days (threshold=25, size=1.49x):**  
- Very low bar to entry: almost any scan hit qualifies
- 49% oversized positions
- This is where money is made — the optimizer learned to be aggressive on hot days
- Corpus: "Fourth week of strong momentum → $5,200+ day with multiple winners"

**COLD days (threshold=77):**  
- Only A+ setups (high bar — 77/100 score required)  
- 39% normal size (significant reduction)
- Exit at T1 (full position, don't chase T2)
- Corpus: "Cold days: Size-reduce. Only take the A+ catalyst with highest premarket volume. Exit at T1."

**CHOP days (threshold=66, size=0.46x):**  
- Interesting: threshold is LOWER than cold (66 vs 77), but size is slightly larger (0.46 vs 0.39)
- This suggests chop days get slightly MORE trades but at half size
- Note: chop = 2% of days in corpus — small sample, optimizer may have noise here

**News scoring (best trial values):**
```python
f_news_none_pts = 2        # no news = small positive (not a killer)
f_news_tier1_pts = 13      # major catalyst = big boost
f_news_tier2_pts = 11      # secondary catalyst = large boost  
f_news_unknown_pts = 5     # unknown news = moderate (benefit of doubt)
```
Corpus confirms: no-news gaps work (SBFM +$20K, OCEA +$11K). News boosts score but non-news setups are valid with strong vol/float.

**Rel-vol scoring (best trial):**
```python
f_relvol_pts_5x = 7       # 5x relative volume
f_relvol_pts_10x = 14     # 10x — big jump here
f_relvol_pts_25x = 15     # 25x — slightly more
f_relvol_pts_100x = 16    # 100x — diminishing returns above 25x
```
The 5x→10x jump is large (7→14). 10x is the inflection point where momentum is strong enough to trust.

---

## Section 6: Price Range Filter

| Param | Default | Optimized |
|---|---|---|
| `a_min_price` | ~1.0 | **1.32** |
| `a_max_price` | ~20.0 | **17.1** |

Tighter price range than default. Excludes:
- Very cheap stocks (<$1.32): too volatile, unpredictable tape
- Expensive stocks (>$17): slower movement, less % upside on momentum

---

## Section 7: Optuna B-Series (Entry) Stop/Buffer

| Param | Optimized |
|---|---|
| `b_min_rr_ratio` | **1.68** |
| `b_stop_buffer` | **0.085** ($0.085 below trigger = stop) |

Minimum R:R ratio at entry = 1.68:1. Tighter than default, ensures every entry has positive expected value before the trade begins.

---

## Section 8: What to Change in models.py (Concrete Defaults)

These are the specific model defaults to update based on 292-trial findings:

```python
# trading/models.py — ScannerConfig
min_price: float = 1.32        # was ~1.0
# max_price: float = 17.1     # verify existing field name

# trading/models.py — EntryConfig  
enable_macd: bool = True        # was False
enable_micro_pullback: bool = True  # was True (no change)
enable_abcd: bool = True        # was varies (enable, scoring will filter)
enable_bull_flag: bool = False  # was varies (disable)
enable_ema9: bool = False       # was varies (disable)
enable_vwap_break_curl: bool = False  # was varies (disable)
enable_flat_top: bool = True    # keep True
enable_dip_buy: bool = True     # keep True
enable_trend: bool = True       # was varies (enable)
min_rr_ratio: float = 1.68     # was varies
stop_buffer: float = 0.085     # was varies

# trading/models.py — ExitConfig
enable_selling_pressure: bool = True   # was False — CRITICAL CHANGE
selling_pressure_ratio: float = 2.5    # was 2.0
selling_pressure_qty_pct: float = 0.91 # was 0.50 — CRITICAL CHANGE  
target1_ratio: float = 1.28            # was 2.19 — CRITICAL CHANGE
target1_qty_pct: float = 0.45          # was 0.30 — CRITICAL CHANGE
enable_macd_flip_exit: bool = True     # was False (+ bug fix required, see §3)
time_decay_hour: int = 11              # was 10 (10:30 → 11:00)

# trading/models.py — AddOnConfig
add_pct_tier1: float = 0.30           # was 0.25
add_pct_tier2: float = 0.28           # was 0.25
max_add_ons: int = 3                  # verify
time_cutoff_minute: int = 19          # add-on cutoff = 9:49 AM
enable_micro_pb_add: bool = False     # was varies
enable_new_high: bool = True          # was varies
enable_vwap_retest: bool = True       # was varies
enable_whole_dollar_add: bool = True  # was varies
hot_market_multiplier: float = 1.26  # was 1.0

# trading/models.py — ScoringConfig
threshold_cold: int = 77       # was 70 — SIGNIFICANT CHANGE
threshold_hot: int = 26        # was varies (low bar for hot days)
size_hot: float = 1.49         # was 1.0 — SIGNIFICANT CHANGE (oversize hot days)
size_cold: float = 0.39        # was varies
```

---

## Section 9: What NOT to Change

- `account_size`, `risk_pct`, `max_position_pct` — not tuned, keep defaults
- `b_enable_dip_buy = True` — already correct
- `f_size_neutral = 0.75` — already correct
- Pattern detection logic itself — only the THRESHOLDS and TOGGLES above

---

## Section 10: Implementation Priority Order

1. **[CRITICAL] Fix MACD bug** in `entry_engine.py` — checking histogram instead of line (§3)
2. **[CRITICAL] Enable selling pressure** with ratio=2.5, qty=0.91 (§2)
3. **[CRITICAL] Lower target1_ratio** from 2.19 to 1.28, raise qty_pct to 0.45 (§2)
4. **[HIGH] Increase size_hot to 1.49** and lower threshold_hot to 26 (§5)
5. **[HIGH] Raise threshold_cold to 77** (§5)
6. **[HIGH] Enable MACD flip exit** (after bug fix in §3)
7. **[MEDIUM] Update add-on params** — tier sizing, time cutoff, trigger flags (§4)
8. **[MEDIUM] Update toggles** — disable bull_flag, ema9, vwap_break_curl (§1)
9. **[LOW] Update price range** — min 1.32, max 17.1 (§6)

---

## Section 11: Out-of-Sample Validation Plan

After Optuna run completes (500 trials, ETA ~3h):
1. Extract best config parameters
2. Run `simulate_date_range.py` on **Oct 2025 – Mar 2026** (6 months, NOT in training set)
3. Compare: +$14,166 / 181 days in-sample vs OOS result
4. If OOS degrades by >50%, suspect overfitting; reduce param count, re-run
5. If OOS is within 75% of in-sample, configuration is solid

**Phase 2 (after OOS validation):**
- Lock 50+ low-importance params at best-trial values
- Re-run Optuna with only top-10 params in ±25% range
- Expected: faster convergence, less noise, tighter confidence interval

---

## Appendix: Corpus Page → Implementation Mapping

| Concept Page | Param(s) Informed | Key Finding |
|---|---|---|
| concept_gap_and_go.md | a_enable_premarket_gain | News "strongly preferred" not required; 30-40% no-news wins |
| concept_entry_trigger_taxonomy.md | b_enable_* toggles | abcd=42.9% but scoring filters it; vwap-break/curl conflicts with MACD gate |
| concept_front_side_back_side.md | b_enable_macd, c_enable_macd_flip_exit | Bug fix: check MACD LINE not histogram; flip exit IS valid |
| concept_stop_management.md | c_target1_ratio, c_selling_pressure_* | MACD exit at 75% when histogram flips profitable; stop below trigger level |
| concept_add_on_mechanics.md | e_add_pct_tier*, e_time_cutoff | 52.3% of trades have adds; Add2=25%; never add after 10:30 |
| concept_market_temperature.md | f_threshold_*, f_size_* | HOT=46% of days; COLD threshold raised to 77; hot size +49% |
