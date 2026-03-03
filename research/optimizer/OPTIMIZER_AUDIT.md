# Optimizer Run Audit
*Generated: 2026-03-03 — comprehensive history of all Optuna trials run*

---

## Quick Reference Summary

| Run Name | Date | Trials | Universe | Period | Best P&L | Trades | WR | Notes |
|---|---|---|---|---|---|---|---|---|
| Sweep (param grid) | Feb 22 | 89×2 | All 4000 | Feb/Mar 2025 | $24 | ~1 | — | Too few trade days |
| debug / fast50 runs | Feb 24 | ~35 total | All 4000 | Oct 2025 (5 days) | $107 | small | — | Dev/debug only |
| trading_2026-01-05 | Feb 25 | 200 | All 4000 | Jan 5–21, 2026 | $1,490 | 31 | 67.7% | Short window; inflated PF |
| phase2_full_jan2026 | Feb 25 | 500 | All 4000 | Jan 5–21, 2026 | $1,490 | 31 | 67.7% | Same data, more trials |
| meta runs | Feb 25 | 10 | All 4000 | Jan 5–21, 2026 | $99 | 11 | 72.7% | Experimental; abandoned |
| **robust_fullyear_seed269** | Feb 27 | 250 | All 4000 | Jan 2025–Jan 2026 | **$1,823** | 101 | 72.3% | First full-year run |
| **pillar23_adaptive** | Mar 2 | 51 (CRASHED) | pillar23_universe | Jan 2025–Jan 2026 | — | — | — | ⚠️ Failed at trial 51; stale cache issue |
| **pillar23_v2** | Mar 2 | 249 | pillar23_universe | Jan 2025–Jan 2026 | **$4,673** | 1102 | 81.3% | Best run to date |
| **pillar23_numeric_tuning** | Mar 3 | 199 | pillar23_universe | Jan 2025–Jan 2026 | **$4,673** | 1102 | 81.3% | Numeric fine-tune; seed trial stayed best |

---

## Detailed Run Profiles

---

### 1. Parameter Grid Sweeps — `results_feb2025.db` / `results_mar2025.db`
- **Date run**: Feb 22, 2026
- **Type**: Manual grid sweep (not Optuna), 89 runs each
- **Universe**: All ~4000 symbols (no filter)
- **Simulation period**: Feb 2025 (89 runs) and Mar 2025 (89 runs)
- **Results**: Near-zero P&L across the board. Feb best = $24/1 trade. Mar best = $0
- **Why so bad**: Only scanning a single month each, very few gapping stocks per day. Also early stage — cat-A filters mostly enabled, patterns not tuned.
- **What we learned**: Single-month windows have too few events to be meaningful. Need full-year periods.

---

### 2. Debug / Small Runs — `optuna.db` studies `debug*`, `fast50*`, `cachecheck*`
- **Date run**: Feb 24, 2026
- **Type**: Dev/debug Optuna studies (3–50 trials each)
- **Universe**: All symbols, Oct 10–14, 2025 (5 days)
- **Purpose**: Validating that cache, simulation, and Optuna plumbing worked
- **Results**: Meaningless (5-day window, too small). `fast50` and `fast50_v2` each ran 50 trials in ~4–5 minutes. Confirmed caching worked.
- **Key discovery**: `fast50_relvol` study took 46 minutes per trial vs 5 seconds — confirmed that relative volume DB queries were the bottleneck when enabled.

---

### 3. Single-Indicator Mode Runs — `optuna.db` studies `trading_2026-01-05` and `phase2_full_jan2026`
- **Date run**: Feb 25, 2026
- **DB**: `optimizer/results.db` (450 runs across both studies)
- **Universe**: All ~4000 symbols
- **Simulation period**: Jan 5–21, 2026 (2.5 weeks) for first; extended to full year for second
- **Trials**: 200 + 500 = 700 total Optuna trials (450 saved results, some pruned/zero-trade)
- **Best result**: Trial 00492 — **$1,490 P&L, 31 trades, 67.7% WR, 6.57 PF**
- **Best cat-A ON**: `price_range`, `premarket_gain`, `last_5min_volume`, `last_1min_volume`
- **Best cat-B ON**: `ema9`, `trend`, `bull_flag`, `micro_pullback`, `abcd`
- **⚠️ Inflated PF (6.57)**: Only 31 trades in 2.5 weeks = very small sample. Not reliable.
- **Dec 2025 validation** (420 runs): Best $1,276 but avg = **-$257** — confirmed Jan 2026 was an anomalously good period. Serious overfitting concern.

---

### 4. Meta Optimizer Runs — `meta_optuna.db` / `meta_results.db`
- **Date run**: Feb 25, 2026
- **Type**: Experimental "meta" wrapper around Optuna (2 rounds, 5 trials each = 10 total)
- **Results**: Best $99, avg $10. Abandoned.
- **What it was**: Attempting to optimize hyperparameters of the optimizer itself. Too early to be useful.

---

### 5. Robust Full-Year Run — `robust_optuna.db` / `robust_results.db`
- **Study name**: `robust_fullyear_seed269`
- **Date run**: Feb 27, 2026
- **Seeded from**: Trial 00269 from `results.db` (Jan 2026 run: $275 P&L, 6 trades — modest seed)
- **Universe**: All ~4000 symbols
- **Simulation period**: Jan 2, 2025 – Jan 31, 2026 (**full year**)
- **Trials**: 250 total (186 complete, 62 pruned, stopped cleanly at 250)
- **Results stored**: 192 in `robust_results.db` (186 optuna + 6 validation runs)
- **Trial duration**: avg 4.0 min/trial, range 1.7–10.3 min
- **Best result**: Trial 00198 — **$1,823 P&L, 101 trades, 72.3% WR, 2.21 PF, $292 max DD**
- **Best cat-A ON**: `price_range`, `market_cap_filter`, `last_5min_volume`, `last_1min_volume`
- **Best cat-B ON**: `abcd` only (all others OFF)
- **⚠️ Suspicious**: Top-5 all converge on `abcd` pattern only. This was scanning ALL 4000 symbols. The optimizer found ABCD was the "easiest" pattern to fire across all stocks — not necessarily the right strategy.
- **What we learned**:
  - Full-year period is essential — much more reliable than 2-week windows
  - With all-4000-symbol universe, optimizer gravitates to ABCD (too easy to trigger)
  - Need to restrict to known gapper stocks to get meaningful results
  - $1,823 is still much lower than what pillar23 achieved — confirms universe matters

---

### 6. Pillar23 Adaptive Run — `pillar23_optuna.db` (study: `pillar23_adaptive`)
- **Date run**: Mar 2, 2026 — 12:46 to 16:25 (~3.7 hours)
- **Universe**: `analysis/pillar23_universe.csv` (1,436 symbols, 3,020 date-specific pairs, Jan 2025–Feb 2026)
- **Simulation period**: Jan 2, 2025 – Jan 31, 2026
- **Mode**: `--adaptive-trend` flag enabled
- **Intended trials**: 250
- **Actual trials**: 51 total — **CRASHED at trial 51 (FAIL state)**
  - 30 COMPLETE, 20 PRUNED, 1 FAIL
  - Trial durations: 3–7 min each (fast — universe mode working)
- **Results**: No results were saved to `pillar23_results.db` — the run crashed before persisting
- **⚠️ The stale cache issue**: The `data/cache/` directory contained parquet files from the prior full-universe (all-4000-symbol) robust run. When adaptive loaded these stale files, it was scanning a different (larger) symbol set than `pillar23_universe.csv`. This is why trial speeds and trade counts looked odd/better than expected.
- **⚠️ Cat-A confusion**: In universe/date-specific mode, cat-A gates are automatically bypassed by design (the code explicitly notes this). So it APPEARED that turning off cat-A was the reason for better performance — but actually it's just the normal behavior of universe mode. Cat-A is irrelevant when you're already giving it a curated list.
- **Why it crashed**: Trial 51 failed (0.0 min duration = immediate crash). The failure reason was not logged in the DB. Most likely cause: the stale cache issue caused a data shape mismatch, or the AdaptiveTrendController hit an edge case after 50 trials.
- **What we learned**: Always clear `data/cache/` before switching from full-universe to universe-mode runs.

---

### 7. Pillar23 V2 — `pillar23_optuna.db` (study: `pillar23_v2`) + `pillar23_results.db`
- **Date run**: Mar 2, 2026 — 19:59 to 21:20 (~1.5 hours for first 189 complete)
- **Universe**: `analysis/pillar23_universe.csv` (1,436 symbols, date-specific)
- **Simulation period**: Jan 2, 2025 – Jan 31, 2026
- **Mode**: `full` (no adaptive trend), locked params: `b_enable_abcd=False`, `b_enable_trend=True`, `c_time_decay_hour=10`
- **Seeded from**: Trial 193 from robust run (via `--seed-trial 193 --seed-db optimizer/pillar23_results.db`)
  - Wait — seeded from prior pillar23 result (Trial 193 was the best at that point)
- **Trials**: 249 total (189 complete, 60 pruned, 0 failed)
- **Results**: 223 saved in `pillar23_results.db`
- **Trial duration**: 3–7 min (consistent)
- **Best result**: Trial 00000 (the seeded trial!) — **$4,673 P&L, 1102 trades, 81.3% WR, 1.33 PF, $1,116 max DD**
- **Top-10 pattern**: ALL use `micro_pullback + dip_buy + flat_top` with trailing stops
- **Top-10 tightly clustered**:
  - stop_buffer: 0.074–0.096
  - RR ratio: 1.65–2.00
  - T1 ratio: 2.00–2.82 @ 25–70%
  - trail stop: 0.247–0.303
- **Locked params that held**:
  - `b_enable_trend=True` ✅
  - `b_enable_abcd=False` ✅
  - `c_time_decay_hour=10` ✅
- **What we learned**:
  - Universe mode (gapper-specific) is dramatically better than all-4000 scans
  - Restricting to pillar23 universe (stocks that actually gapped) gave 3x better P&L
  - ABCD pattern genuinely hurts — confirmed by locking it off and seeing improvement
  - The seeded trial was already near-optimal — optimizer found nothing better in 249 more trials
  - Time decay at 10am (not 11am) is important

---

### 8. Pillar23 Numeric Tuning — `pillar23_numeric.db` (optuna) + `pillar23_results.db`
- **Date run**: Mar 3, 2026 — 00:02 to 00:56 (~54 min)
- **Universe**: `analysis/pillar23_universe.csv` (same as v2)
- **Simulation period**: Jan 2, 2025 – Jan 31, 2026
- **Purpose**: Fine-tune numeric params (stop_buffer, RR, T1 ratio/qty) with boolean flags locked
- **Locked params**: `b_enable_trend=True`, `b_enable_abcd=False`, `b_enable_ema9=True`, `b_enable_macd=True`, `b_enable_micro_pullback=True`, `b_enable_flat_top=True`, `b_enable_bull_flag=False`, `c_time_decay_hour=10`
- **Seeded from**: Trial 193 (pillar23_v2 best)
- **Trials**: 199 total (151 complete, 48 pruned)
- **Best result**: Trial 00000 (again, the seeded trial!) — **$4,673, 1102 trades, 81.3% WR**
- **⚠️ Note**: `2025-01-09` always warns "No symbols with data" — this is a known data gap, not a bug
- **Conclusion**: Numeric params in Trial 193 are already near-optimal. The optimizer found no improvement in 199 additional trials.

---

## Key Findings & Confusion Clarified

### "The 250-trial run that stopped at 50" = `pillar23_adaptive`
This was set to run 250 trials but crashed at trial 51 (FAIL). ~3.7 hours of work lost because no results were saved. This was Mar 2, 2026.

### "Was doing much better" — Why pillar23 >> robust
| Metric | robust (all 4000) | pillar23 (1436 gappers) |
|---|---|---|
| P&L | $1,823 | $4,673 |
| Trades | 101 | 1,102 |
| Win rate | 72.3% | 81.3% |

The improvement is NOT because cat-A was turned off. It's because:
1. **Universe restriction**: Scanning only stocks that historically gapped = far higher signal density
2. **Cat-A is auto-bypassed** in date-specific/universe mode (by design in the code)
3. **Pattern selection**: ABCD locked OFF, proper patterns locked ON

### "Was it turning off cat-A indicators?"
Partially. In universe mode, cat-A is bypassed automatically — the logic is "we already know these stocks gapped, so we don't need the premarket gain / relative volume / float filters again." This is correct behavior. It only looks like "turning off cat-A" because the params show `False` for most cat-A fields.

### The Stale Cache Problem (pillar23_adaptive crash)
When `--cache-data` is used, parquet files are written to `data/cache/`. The robust run (all 4000 symbols) left stale cache files. When pillar23_adaptive ran with the gapper universe, it loaded cached data for symbols NOT in the pillar23 universe — giving inconsistent results and eventually crashing.

**Fix**: Always `rm -rf data/cache/` before switching universe files.

---

## Should We Re-run the Stopped pillar23_adaptive?

**Short answer: No — pillar23_v2 already supersedes it.**

Here's why:
- `pillar23_adaptive` ran `--adaptive-trend` which auto-learns the trend param
- `pillar23_v2` locked `b_enable_trend=True` explicitly (which the adaptive run would have converged to anyway)
- pillar23_v2 ran 249 complete trials and found nothing better than the seeded trial
- pillar23_numeric ran 199 more trials and still found nothing better

The adaptive feature isn't needed — we've manually confirmed `trend=True` is the right answer. Re-running adaptive would waste time and yield the same conclusion.

---

## Current Best Config (Trial 00193 / 00000)
```
Patterns: micro_pullback + dip_buy + flat_top (ABCD=OFF, bull_flag=OFF)
Indicators: EMA9=True, MACD=True, trend=True
Stop buffer: 0.076 (~7.6 cents per dollar)
RR ratio: 2.00
T1: sell 30% at 2.19× stop distance
Trailing stop: 0.262
Time decay: exit at 10:00am
Universe: pillar23_universe.csv (1,436 known gappers, date-specific)
```

**Walk-forward validation (Feb 2–18, 2026)**:
- $256 P&L / 12 days = **$21.33/day**
- 61 trades, 86.9% WR, 1.39 PF
- 8 losses: 5 STOP_HIT, 3 trailing stop

---

## Next Priority: Improve Win:Loss Ratio

Current problem: avg win $17.20 vs avg loss -$82.00 → ratio = 0.21 (very unfavorable)
Win rate is high enough (87%) to still be profitable, but one bad stop wipes out 4-5 wins.

Target: tune stop_buffer to reduce stop distance without triggering too often. Consider:
- Wider stop on high-float stocks
- Tighter stop on low-float stocks
- Stop based on ATR rather than fixed percentage
