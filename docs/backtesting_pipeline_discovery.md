# Backtesting Pipeline — Discovery & Speed Analysis

**Purpose**: Comprehensive doc for Opus-level reasoning on how to drastically improve
the optimization / backtesting pipeline. All claims cite exact file:line.  
**Written**: 2026-06-04 by Sonnet discovery pass  
**Read alongside**: `production/simulator/simulation_engine.py`, `production/trading/orchestrator.py`,
`research/optimizer/optuna_run.py`, `research/optimizer/simulate_one.py`

---

## 1. What We're Optimizing

We're tuning ~60 parameters (after locking 56 low-importance ones via fANOVA) of a
day-trading simulator against Ross Cameron's gap-and-go strategy on 2021–2025 data.
The optimizer is Optuna TPE (Bayesian). The objective is a "consistency" score
(see `research/optimizer/objective_functions.py:166–173`): `total_pnl × green_rate ×
payoff_factor × sample_factor - 0.5 × drawdown`, which rewards sustainable
day-over-day profitability vs one-lucky-day outliers.

---

## 2. Current Architecture — End-to-End Flow

```
optuna_run.py                      (Optuna driver)
  └─ _build_config_from_trial()    (maps trial → RunConfig, ~60 suggest_* calls)
  └─ run_date_range()              simulate_one.py:31
       └─ for each day in trial:
            └─ SimulationRunner    simulation_engine.py:125
                 ├─ load_minute_bars()   (data load: parquet or DB)
                 ├─ _build_hot_symbols()  (whole-day pre-filter, O(bars))
                 └─ run()
                      └─ Orchestrator.on_minute()   orchestrator.py:250
                           ├─ _scan_for_entry()
                           │    ├─ qualifies_momentum()  momentum_scanner.py:30
                           │    └─ evaluate_entry()      entry_engine.py
                           └─ _update_positions()
                                └─ evaluate_exit()       exit_engine.py
```

### 2.1 Data Layer

**Source**: TimescaleDB (Docker), `stock_candles_1m` (1-min bars), `stock_candles_1h`
(hourly premarket), `stock_candles_1d` (daily), `rel_vol_cum_cache`, `stock_fundamentals`.

**Caching — 3 levels**:
1. **LRU memory cache** (`_DATA_CACHE`, dict): per-day numpy arrays in RAM.
   Cap = 100 days (`_DATA_CACHE_MAX`, `simulation_engine.py:70`).  
   Populated via pkl on startup (`memory_cache.pkl`, currently 1.7 GB / 100 days).
2. **Parquet disk cache** (`simcache_v2_YYYY-MM-DD.{minute,prior,premarket,fundamentals}.parquet`):
   one set of 4 files per day, 8.4 GB total, 1238 complete days (2021–2025).  
   Loaded when day not in RAM cache (`_load_persisted_cache`, `simulation_engine.py:771`).
3. **DB fallback**: live TimescaleDB query when parquet missing. Used for 2026+ dates.

**Per-day data size**: ~167K–277K minute bars, ~2K–3K symbols.  
**Load time from parquet**: ~1–3s/day (dominant overhead for most trials).

### 2.2 Per-Minute Simulation

For each trading minute (8:00–13:00 ET = 300 bars/day × ~2500 symbols = 750K iterations/day):
- `simulation_engine.py:641–720`: pre-filter — only "hot" symbols evaluated
- `orchestrator.py:260–370`: `_scan_for_entry` → qualifies_momentum → evaluate_entry
- `orchestrator.py:200–258`: `_update_positions` → evaluate_exit

**Hot symbols pre-filter** (`simulation_engine.py:406–449`): scans ALL minute bars once
at load time to find symbols that ever hit gain ≥ 5% and price $1–25. Typically 50–200
symbols/day qualify. This is a look-ahead (sees future bars) but gates are time-forward
in qualifies_momentum, so no incorrect trades result. Key comment at line 421.

**Entry engine**: `production/trading/entry_engine.py` — evaluates 8 patterns
(flat_top, bull_flag, abcd, dip_buy, gap_and_go, vwap_reclaim, orb, micro_pullback),
scoring system, EMA9/MACD indicators. Called once per hot-symbol per minute.

**Exit engine**: `production/trading/exit_engine.py` — time decay, selling pressure,
MACD flip, resistance exit, trailing stop. Called once per open position per minute.

---

## 3. Measured Performance (from trial output logs)

| Metric | Value |
|--------|-------|
| Days/trial (1/week) | 258 |
| Days/trial (2/week) | 516 |
| Trial 1 time (2/week) | ~34 min (2039s) |
| Per-day throughput | ~3.4 days/min from parquet |
| Per-day from DB | ~26s/day (before parquet cache) |
| Trial time (1/week, est.) | ~17 min |
| 250 trials × 17 min | ~70 hours (~3 days) |
| Python PID memory | ~2 GB (pkl loaded) |

**Breakdown of per-day time** (estimated from observed throughput):
- Parquet read + numpy array build: ~1–2s
- `_build_hot_symbols` (numpy loop, O(bars)): <0.1s
- Per-minute orchestrator loop (300 min × hot_syms): ~0.5–1s
- DB rel_vol resolver (cache_data=True → noop): 0s
- Total from parquet: ~2–4s/day

**Bottleneck**: parquet I/O and numpy array construction, NOT the trading logic.

---

## 4. Current Bottlenecks

### B1. Single-process, single-thread
`study.optimize(obj_fn, n_trials=N)` runs one trial at a time.
`optuna_run.py:1110`. Optuna supports `n_jobs=-1` for parallel trials,
but each trial needs DB write access (SQLite) and the LRU RAM cache is
process-local. Would require either:
- Multiple processes (each with own pkl copy → ~2 GB × N processes)
- Or shared memory / Redis cache

### B2. Sequential per-day loop inside each trial
`simulate_one.py:95–165`: days run sequentially. Each day is independent
(no state leaks between days — positions reset each day at
`simulation_engine.py:591–593`). Days are **embarrassingly parallel**.

### B3. Parquet read is the dominant per-day cost
Each day reads 4 parquet files (~5–7 MB total). `pyarrow.parquet.read_table`
then `.to_pylist()` (Python list conversion) at `simulation_engine.py:793`.
`.to_pylist()` is O(rows), creates Python dicts — expensive for 167K rows.
NumPy array build from list at line 796 is also O(rows).

### B4. LRU cache limited to 100 days
`_DATA_CACHE_MAX = 100` (`simulation_engine.py:70`). With 258 days/trial
and different days per trial (stratified sampling), RAM cache hit rate ≈
100/258 = 38%. The remaining 62% reload from parquet every trial.
Increasing this is RAM-limited (currently ~2 GB for 100 days → ~20 GB for 1000 days).

### B5. ~60 tunable params — large search space
TPE needs ~5–10× params for good convergence = 300–600 trials minimum.
Each trial is ~17 min. Even 300 trials = 85 hours.
The fANOVA analysis showed only ~15–20 params are truly high-importance
(scoring weights, scanner thresholds, pattern toggles).

### B6. SQLite for Optuna storage — write contention
`sqlite:///optimizer/optuna.db`. Single-writer SQLite is fine for sequential
trials but blocks parallel workers. PostgreSQL or Redis would unblock `n_jobs > 1`.

### B7. No early stopping within a trial
`early_abort_days = 20` prunes bad configs after 20 days with 0 trades.
But a config that makes trades but has terrible P&L runs all 258 days.
There's no "this trial's objective is clearly worse than current best" check.

---

## 5. What's Already Been Tried / Ruled Out

- **DB queries per symbol per minute**: removed. Before parquet cache, was 600K
  DB connections/day. Now noop via `_noop_rel_vol_resolver` when cache_data=True.
  (`simulation_engine.py:620–622`)
- **Per-day DB backfill of rel_vol_30d**: done (1238 days).
  `research/maintenance/backfill_rel_vol_historical.py`
- **symbol_universe precomputed lists**: tried (oracle mode). Adds 26s/day for
  universe building. Removed from optimizer hot path.
- **Batch rel_vol DB query**: `get_avg_volume_at_time_batch`, replaced per-symbol
  queries. Now bypassed entirely in cache mode.
- **Memory pkl save/load**: `save_memory_cache/load_memory_cache`,
  `simulation_engine.py:~930–960`. Saves LRU dict to pkl for fast restart.
  Currently 1.7 GB / 100 days.
- **Parquet persist optimization**: skip rewriting minute/premarket/fundamentals
  if files already exist; always rewrite prior (may update via 1m fallback).
  `simulation_engine.py:~875–915`.

---

## 6. Potential Speedup Vectors (Sonnet observations — NOT yet evaluated)

### V1. Parallel trials via multiprocessing (estimate: 4–8× speedup)
Optuna supports `study.optimize(fn, n_trials=N, n_jobs=4)` with multiple workers.
Requires: shared Optuna storage (PostgreSQL > SQLite), per-worker parquet reads
(already file-based, safe for parallel reads). RAM: each worker needs ~2 GB pkl
OR workers share via mmap/arrow.
**Blocker**: SQLite write contention. Fix: switch to PostgreSQL (already running
TimescaleDB = PostgreSQL, same container).

### V2. Vectorized multi-day simulation (estimate: 5–20× speedup)
Instead of running days sequentially in Python, preload ALL trial days into one
large NumPy array and vectorize the scanner pre-filter across all days at once.
The per-minute hot-symbol loop is the only stateful part (positions, HOD tracking).
Pure NumPy/Numba/Cython for the scan loop could be 10–50× faster than Python loops.

### V3. Pre-filter parameter space before Optuna (reduce dead trials)
~30–40% of trials prune (0 trades). Root cause: scanner thresholds too tight.
Could pre-validate that `min_premarket_gain × min_relative_volume` combination
produces at least N candidates on a sample of days before running full simulation.
Would cut pruned trial cost from 20-day×3.5s = 70s to <1s.

### V4. Increase `_DATA_CACHE_MAX` with shared memory
Arrow IPC / shared memory (Python `multiprocessing.shared_memory`) could let
multiple workers share the same parquet data without 2 GB × N copies.
PyArrow has `pyarrow.plasma` (deprecated) and `pyarrow.ipc` for zero-copy reads.
Or simply increase to 500–1000 days if RAM allows (server with 32+ GB RAM).

### V5. Numba JIT for per-minute orchestrator loop (estimate: 5–30× inner loop)
`orchestrator.py:_scan_for_entry` and `_update_positions` are pure Python loops
over NumPy arrays. `qualifies_momentum` is 8 conditional checks.
Compiling with `@numba.jit(nopython=True)` could push per-day sim from ~2s → ~0.1s.
**Risk**: Numba doesn't support Python objects (dicts, dataclasses) — would need
to flatten config into scalar arrays. Significant refactor.

### V6. Reduce days/trial further + more trials (tradeoff)
Current: 258 days × 17 min = 250 trials in 70 hrs.
Alternative: 52 days (1/month) × 3.5 min = 500 trials in 29 hrs.
More trials = better TPE convergence. Fewer days/trial = higher variance per trial
but TPE averages across trials. Literature suggests 50–100 days/trial is
sufficient for Bayesian convergence if stratification covers all regimes.

### V7. Two-phase optimization (coarse → fine)
Phase 1: 200 trials on 52 days, gates-only mode (~7 min/trial = 24 hrs).
  → Identify best 20 configs.
Phase 2: 100 trials on 258 days, full mode, seeded from Phase 1 best.
  → Fine-tune numerics in proven gate region.
This is similar to what we did with `mega_120params_v3` (3000 trials on 2025 only)
but formalized with the 5yr dataset.

### V8. Bayesian alternative: SMAC3 / HyperOpt / Ax
Optuna TPE is not the only Bayesian optimizer. Alternatives:
- **SMAC3**: Random Forest surrogate, better for mixed int/float/categorical,
  handles conditional params (e.g. b_bull_flag params only matter when b_enable_bull_flag=True).
  Optuna TPE treats conditional params as independent — wastes trials.
- **Ax (Facebook)**: Gaussian Process, better sample efficiency for <200 trials.
- **BoTorch (Facebook)**: Batched BO, designed for parallel evaluation.
Conditional param structure is significant here: ~40 of 60 tunable params
are conditioned on a boolean gate. TPE ignores this → wastes budget.

### V9. Pre-screen with cheap proxy objective
Run each config on 5 "canary" days (high-volatility, well-known good/bad days)
before committing to 258 days. Canaries: 2021-01-27 (GME peak), 2021-02-24
(market dump), any high-momo day. If proxy objective < threshold, prune immediately.
Cost: 5 days × 3.5s = 17s vs 258 days × 3.5s = 903s. 50× speedup for bad configs.

### V10. Parquet → Arrow IPC format (zero-copy reads)
Current: `pq.read_table(path).to_pylist()` (`simulation_engine.py:793`).
`to_pylist()` converts columnar Arrow → Python dicts → numpy array.
Alternative: keep data in Arrow format, use `table.column('close').to_pyarray()`
or direct numpy via `table['close'].to_pylist()`. Or switch to Feather/IPC format
which allows memory-mapped zero-copy reads (no deserialization at all).

---

## 7. Parameter Space Analysis (from locked_params_v2.json fANOVA)

**56 locked params** (low importance, convergence ratio ≥ 0.70 or plateau ≥ 70%):
- 7 booleans with strong bias (e.g. b_enable_rr=True, b_enable_ema9=True)
- 38 numeric with high convergence (e.g. f_pattern_vwap_break_curl=15, locked at corpus values)
- 11 numeric plateau (wide stable region — any value works, e.g. m_hod_tol=0.023)

**~60 tunable params remaining** approximate breakdown:
- Category A scanner: 5 (min_price, max_price, min_premarket_gain, min_relative_volume, max_float)
- Category B entry: ~20 (5 pattern toggles, 15 numeric thresholds)
- Category C exit: ~12 (4 toggles, 8 numerics)
- Category D temperature: 8 (thresholds and size multipliers)
- Category E add-on: 8 (4 toggles, 4 sizes)
- Category F scoring: ~7 (thresholds, size multipliers — unlocked ones)
- Category M momentum: 3 (min_intraday_gain, scan_end_hour, hod_tol)

**High-leverage params** (fANOVA top importance in mega_120params_v3, 2025 data):
These are the params TPE should focus on most. The locked params file at
`research/optimizer/locked_params_v2.json` documents which were locked.

---

## 8. Data Coverage Gaps

| Year | Status |
|------|--------|
| 2021 Jan–Jul | Full (3,300+ symbols) |
| 2021 Jan 4 | **Broken** (no prior_close possible — blacklisted in DateSampler) |
| 2021 Jan 5 | 27.6% NULL rel_vol (only 1 prior day of history) |
| 2021–2022 rel_vol | Phase 2 complete but early days have partial NULL (new symbols) |
| 2024 Jan–Nov | **GAP** — no 1m bars. DateSampler correctly skips (min_symbols=500 filter) |
| 2024 Dec | Partial (387 symbols) — likely passes min_symbols=500? Needs check |
| 2025 Jan–Dec | Full |
| 2026 Jan–Mar | 1m bars exist, but prior.parquet missing (54 days incomplete cache) |

Coverage note: `stock_candles_1d` starts 2021-06-02. Prior close for Jan–May 2021
uses 1m fallback (`simulation_engine.py:476–502`).

---

## 9. Key Files Quick-Reference

| File | Purpose | Key lines |
|------|---------|-----------|
| `research/optimizer/optuna_run.py` | Optuna driver, search space | 170–646 (search space), 706–807 (objective) |
| `research/optimizer/simulate_one.py` | Per-trial date-range runner | 31–232 |
| `research/optimizer/objective_functions.py` | Objective formulas | 97–173 |
| `research/optimizer/date_sampler.py` | Stratified day sampling | 47–201 |
| `research/optimizer/locked_params_v2.json` | 56 locked params | all |
| `production/simulator/simulation_engine.py` | Core sim engine | 225 (load), 406 (hot_symbols), 574 (run) |
| `production/trading/orchestrator.py` | Per-minute logic | 260 (_scan_for_entry), 200 (_update_positions) |
| `production/trading/momentum_scanner.py` | qualifies_momentum() | 30–88 |
| `production/trading/entry_engine.py` | Pattern detection | all |
| `production/trading/exit_engine.py` | Exit logic | all |
| `research/optimizer/data/cache/` | Parquet + pkl cache | 8.4 GB, 1238 days |

---

## 10. Questions for Opus Reasoning

1. **Parallelism**: Given TimescaleDB is already PostgreSQL, can we reuse that as
   Optuna storage and run `n_jobs=4` with workers sharing parquet files read-only?
   What's the RAM strategy — 4 × 2 GB pkl copies, or shared Arrow IPC?

2. **Conditional params**: Should we switch from Optuna TPE to SMAC3 or Ax to
   properly model the conditional parameter structure (e.g. bull_flag params only
   active when b_enable_bull_flag=True)?

3. **Canary days**: Is a 5-day pre-screen proxy reliable enough to prune bad configs
   without introducing selection bias toward those 5 specific days?

4. **Days/trial tradeoff**: What's the minimum days/trial for statistical validity
   with the consistency objective? Is 52 days (1/month) sufficient or does regime
   coverage require ≥ 100?

5. **Numba viability**: The orchestrator uses Python dicts (bar, history, fundamentals).
   Would the refactor cost to make it Numba-compatible be worth 10–30× speedup?
   Or is a C extension / Cython wrapper more practical?

6. **Two-phase**: Should Phase 1 (gates) use `mode=gates-only` (fixed numerics) or
   `mode=full` with reduced days? gates-only cuts the search space to ~10 booleans
   but might miss interactions between gate-numeric combinations.

7. **Objective stability**: The `consistency` formula multiplies 3 factors
   (green_rate, payoff_factor, sample_factor). With only 258 days and 5+ trades/day
   average, is sample_factor close enough to 1.0 to not distort rankings?
   `objective_functions.py:163–173`.

8. **Alternative simulation approach**: Instead of day-by-day sequential simulation,
   could we vectorize across symbols? E.g. precompute all entry signals as a
   DataFrame (symbol × time → signal), then apply exit logic in batch.
   This would change the architecture significantly but could be 10–100× faster.
