# Repository Reorganization Plan
**Goal**: Prepare for live paper trading by separating production code from analysis/experiment code, removing unused artifacts, and improving navigability.

---

## Current State Analysis

### Disk Usage
- `venv/` (345M) — Virtual environment, can be .gitignore'd if not already
- `optimizer/` (63M) — Contains 7+ database files from different experimental runs
- `data/` (49M) — Data collector & backfill scripts
- `database/` (43M) — **DUMP**: 30+ one-off analysis scripts + logs
- `analysis/` (3.9M) — Universe building scripts + generated CSV outputs
- `archive/` (289K) — Already exists; some deprecated code

### Code Quality Issues
1. **database/** is a dumping ground — 22 Python scripts doing analysis, exploration, sweeping
2. **optimizer/** has 44MB+ database artifacts that shouldn't be version-controlled
3. **analysis/** mixes code (scripts that generate) with outputs (CSVs that get regenerated)
4. **Root level** has diagnostic/one-off scripts floating around
5. **No clear separation** between production (what runs live) vs research (what validates it)

---

## Proposed New Structure

```
Stock-Picker/
│
├── production/              ← Everything needed for LIVE TRADING
│   ├── trading/             (entry_engine, exit_engine, patterns, indicators, models, portfolio_manager)
│   ├── simulator/           (simulation_engine, simulate_date, simulate_date_range)
│   ├── backend/             (Flask app, scanner, data_feed)
│   ├── services/            (fetch_fundamentals, fetch_stocks_1_to_20, Alpaca/Finnhub APIs)
│   ├── data/
│   │   ├── collector/       (collect_data.py — lives data — real-time collection)
│   │   └── backfill/        (backfill_optimized.py, fill_gaps.py — for initial/gap-fill DB loads)
│   ├── frontend/            (index.html, app.js, style.css)
│   ├── utils/               (trading_calendar, query_helpers, backtest_scanner)
│   ├── tests/               (unit tests for production code)
│   └── config.py            (main configuration)
│
├── research/                ← Analysis, optimization, diagnostics (not for live trading)
│   ├── optimizer/           (Optuna sweeps, parameter tuning)
│   │   ├── results/         (cleaned: move old .db files here or delete)
│   │   └── *.py             (optuna_run, meta_optimizer, analyze, etc.)
│   │
│   ├── analysis/            (Universe building, regime analysis)
│   │   ├── scripts/         (build_gapper_universe.py, create_pillar23_universe.py, etc.)
│   │   └── outputs/         (generated CSVs — should NOT be version-controlled)
│   │
│   ├── database_analysis/   (MOVE HERE from database/)
│   │   ├── find_*.py        (find_gap_up_events, find_top_gappers_month, etc.)
│   │   ├── analyze_*.py     (analyze_gap_run_patterns, analyze_pre_gap_features, etc.)
│   │   ├── generate_*.py    (generate_daily_gaprun_universe, etc.)
│   │   ├── sweep_*.py       (parameter sweeps)
│   │   └── README.md        (document purpose of each script)
│   │
│   └── maintenance/         (MOVE HERE from maintenance/)
│       ├── *.py             (db_status, sanity_check, check_timezone, exhaustive_data_audit)
│       └── diagnostics/     (one-offs like debug_arbe.py, check_hour_data_coverage.py)
│
├── archive/                 ← Old/deprecated code (but kept as safety net)
│   ├── (existing deprecated code)
│   ├── old_analysis/        (research scripts that are no longer used)
│   └── README.md            (explain what's here and why)
│
├── strategy/                ← Documentation (unchanged)
│   ├── UTS_*.md
│   ├── CATEGORY_C_GAP_ANALYSIS.md
│   └── SIMULATION_OPTIMIZATION_PLAN.md
│
├── .github/                 ← GitHub workflows (if you have any)
│
├── docs/                    ← NEW: Project documentation
│   ├── ARCHITECTURE.md      (system design overview)
│   ├── SETUP.md             (how to set up locally)
│   ├── DATA_PIPELINE.md     (how data flows through the system)
│   └── TRADING_RULES.md     (entry/exit rules reference)
│
├── .gitignore               (ensure venv/, *.db, *.parquet, .env are ignored)
├── README.md                (project overview)
├── requirements.txt
├── ROADMAP.md
└── setup.py / pyproject.toml (if you want to make it installable)
```

---

## Detailed Migration Plan

### TIER 1: Safe to Move to `research/`
These are clearly analysis/diagnostic scripts not used in live trading:

#### Move to `research/database_analysis/`:
- `database/analyze_gap_run_patterns.py`
- `database/analyze_pre_gap_features.py`
- `database/analyze_single_day_coverage.py`
- `database/backfill_rel_vol_30d.py` ⚠️ (used for rel_vol backfill, but only at setup time)
- `database/bootstrap_single_day_data.py` ⚠️ (one-time setup)
- `database/build_gap_run_feature_set.py`
- `database/build_rel_vol_cum_cache.py` ⚠️ (one-time setup)
- `database/compare_prescreens.py`
- `database/diagnose_data_coverage.py`
- `database/find_best_simulation_windows.py`
- `database/find_gap_up_events.py`
- `database/find_top_gappers_month.py`
- `database/generate_daily_gaprun_universe.py` ✅ (used frequently for universe building)
- `database/generate_monthly_gaprun_top100_lists.py` ⚠️ (historical, one-off)
- `database/generate_true_top_gappers.py`
- `database/historical_tradable_stocks.py`
- `database/prototype_prescreen_filters.py`
- `database/summarize_gap_up_events.py`
- `database/sweep_*.py` (all 3 sweep scripts)

#### Move to `research/maintenance/diagnostics/`:
- `debug_arbe.py` (debugging one-off)
- `check_hour_data_coverage.py` (diagnostic)
- `check_tradable_stocks.py` (diagnostic)
- Anything currently in `maintenance/exhaustive_data_audit.py`

#### Keep in `production/data/backfill/`:
- `backfill_optimized.py` ✅ (initial historical backfill, may need to run again)
- `fill_gaps.py` ✅ (gap detection/filling, part of normal ops)
- `backfill_gappers.py` ⚠️ (specialized gapper backfill — move to `research/` if not actively used)
- `backfill_warmup.py` ⚠️ (pre-market warm-up fill — move to `research/` if not actively used)

#### Move to `research/analysis/scripts/`:
- `analysis/build_gapper_universe.py`
- `analysis/compare_daily_universes.py`
- `analysis/create_pillar23_universe.py`
- `analysis/generate_report.py`
- `analysis/premarket_day_comparison.py`

#### Move CSV outputs to `.gitignore`:
All CSVs in `analysis/` should be in `.gitignore` because they're **regenerated**:
- `daily_gaprun_symbols.csv`
- `daily_gaprun_universe.csv`
- `daily_signals.csv`
- `daily_signals_with_detection.csv`
- `gapper_universe.csv`
- `pillar23_trial_results.csv`
- `universe_comparison*.csv`
- `premarket_day_features.csv`
- etc.

**EXCEPTION**: Keep `pillar23_universe.csv` and `master_gappers.csv` (if they exist) in repo **with documentation** since they're manually curated/selected universe files used for simulations.

---

### TIER 2: Database Artifacts to Remove from Repo
These are experiment results that bloated the repo. **Archive locally if you want, but don't version-control**:

#### Delete / Don't Commit:
- `optimizer/optuna.db` (3.8M) — old experimental results
- `optimizer/results.db` (7.4M) — old experimental results
- `optimizer/results_feb2025.db` (212K) — old results
- `optimizer/results_mar2025.db` (212K) — old results
- `optimizer/robust_results.db` (3.3M) — old results
- `optimizer/meta_optuna.db` (168K)
- `optimizer/meta_results.db` (72K)
- `optimizer/pillar23_optuna.db` (1.4M)
- `optimizer/pillar23_numeric.db` (704K) — old numeric confirmation runs
- **KEEP**: `optimizer/pillar23_results.db` (**44M** — but understand this is the main results, document it)

#### Logs to remove:
- `database/collector.log*` (all old log files)

---

### TIER 3: Markdown/Documentation Cleanup
These audit/fix documents should be consolidated:

- `FILE_ORGANIZATION.md` → Merge into `docs/ARCHITECTURE.md` (this is the reorganization)
- `IMPORT_FIXES_SUMMARY.md` → Keep in root or archive (historical fix doc)
- `POSITION_SIZING_FIX.md` → Move to `docs/TRADING_RULES.md` or `production/trading/`
- `RELATIVE_VOLUME_AUDIT.md` → Move to `docs/DATA_PIPELINE.md`
- `TIMESCALE_STORAGE_ANALYSIS.md` → Move to `docs/` or `production/data/`
- Keep `ROADMAP.md` in root
- Keep `strategy/` docs where they are

---

## Recommended `.gitignore` Updates

Add these to `.gitignore`:

```gitignore
# Virtual environment
venv/
.venv/

# Experiment artifacts (keep locally, don't commit)
optimizer/*.db
optimizer/logs/
optimizer/*.csv
research/optimizer/results/

# Generated analysis outputs (regenerated on demand)
analysis/*.csv
research/analysis/outputs/

# Cache files
data/cache/
simulator/__pycache__/
trading/__pycache__/

# Environment
.env
.env.local

# IDE
.vscode/
.idea/
*.pyc

# OS
.DS_Store
Thumbs.db

# Test coverage
.coverage
htmlcov/

# Jupyter
.ipynb_checkpoints/
```

---

## Implementation Steps (Recommended Order)

### Phase 1: Prepare (No Deletions Yet)
1. Create `production/`, `research/`, `docs/` directories
2. Create `research/database_analysis/`, `research/analysis/scripts/`, `research/analysis/outputs/`, `research/maintenance/`, `research/maintenance/diagnostics/`
3. Update `.gitignore` with all the patterns above
4. Create `docs/` markdown files (ARCHITECTURE.md, etc.)

### Phase 2: Move Non-Production Code
1. Move database analysis scripts → `research/database_analysis/`
2. Move analysis code → `research/analysis/scripts/`
3. Move diagnostic scripts → `research/maintenance/diagnostics/`
4. Move `maintenance/` → `research/maintenance/`
5. Move production code → `production/` (backend, trading, simulator, data/collector, data/backfill, services, frontend, tests, utils)
6. Create symlinks or update `sys.path` in entry points so imports still work

### Phase 3: Clean Up
1. Update `config.py` path references if needed
2. Update import paths in `simulator/simulate_date_range.py` and `simulate_date.py`
3. Test that `simulator/simulate_date.py` and `simulate_date_range.py` still work
4. Test that `backend/app.py` still runs
5. Test that `services/fetch_fundamentals.py` still works

### Phase 4: Archive Old Experiments (Optional)
1. Create `.archived/` locally (not in repo) with copies of old .db files
2. Document which run produced which results (in a local Excel or text file)
3. Delete old .db files from repo (keep pillar23_results.db)

### Phase 5: Documentation
1. Update README.md with new structure
2. Add `docs/ARCHITECTURE.md` explaining the separation
3. Add `production/README.md` explaining what goes into production
4. Add `research/README.md` explaining how to use analysis scripts

---

## Files to Archive (Safe to Move Now)

Based on git history and usage patterns, these are **likely unused**:

**SAFE TO ARCHIVE** (low confidence in use):
- `data/backfill/backfill_gappers.py` — specialized gapper backfill, not in recent commits
- `data/backfill/backfill_warmup.py` — premarket warmup, unclear if still used
- `database/backfill_with_daily_stocks.py` — old backfill strategy
- `database/bootstrap_single_day_data.py` — one-time setup
- `services/fetch_stocks_in_price_range.py` — not imported anywhere
- `services/fetch_stocks_1_to_20.py` — may be superseded by fundamentals fetch

**KEEP** (clearly used):
- `trading/` — All core trading modules
- `simulator/simulation_engine.py` — Core backtester
- `backend/app.py` — Live Flask app
- `data/collector/collect_data.py` — Real-time data collection
- `data/backfill/backfill_optimized.py` — May need to run again for new symbols
- `services/fetch_fundamentals.py` — Active (fetches float/market cap)

---

## Summary: What to Delete vs. Archive vs. Keep

| Action | Files |
|--------|-------|
| **Keep in Production** | `trading/`, `simulator/`, `backend/`, `frontend/`, `services/fetch_fundamentals.py`, `data/collector/`, `data/backfill/backfill_optimized.py`, `data/backfill/fill_gaps.py`, `utils/`, `tests/` |
| **Move to Research** | 22 database analysis scripts, 5 analysis scripts, 3 diagnostic scripts |
| **Delete from Repo** | All .db files except `pillar23_results.db`, all generated CSVs, old log files |
| **Archive Locally** | Keep copies of old optimizer runs, old backfill scripts |
| **Update .gitignore** | Add venv/, *.db, generated CSVs, caches |

---

## Benefits After Reorganization

1. **Clarity**: New contributor can immediately see what's production vs. research
2. **Smaller Repo**: Removing .db files shrinks repo from ~500M to ~50-100M (mostly code)
3. **Easier Deployment**: `production/` can be containerized/deployed as-is
4. **Maintainability**: Research experiments won't pollute the main codebase
5. **Clear Separation**: Entry points (`simulator/`, `backend/`) are obvious
6. **Live Trading Ready**: Everything needed for paper trading is in one place

---

## Safety Notes

- **No deletions are permanent** if you keep `.archived/` directory locally
- **Git history is preserved** — you can always recover deleted files from git log
- **Move before delete** — First move to `research/`, run tests, then can delete old locations
- **Test imports** — After moving, test that all imports still work (especially `simulator/`)

---

## Questions to Answer Before Proceeding

1. **`backfill_gappers.py` and `backfill_warmup.py`**: Are these still actively used, or can they move to research?
2. **`optimizer/*.db` files**: Keep all, delete all except pillar23_results.db, or move to local archive?
3. **Symlinks vs. Imports**: After moving, should we use symlinks in repo or update import paths?
4. **Database logs**: Safe to delete `database/collector.log.*` files?
5. **CSV outputs**: Which CSVs (if any) should be committed? (E.g., should `pillar23_universe.csv` be in repo?)
