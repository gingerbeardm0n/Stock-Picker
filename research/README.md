# Research & Analysis

This folder contains experimental code, parameter optimization, and analysis scripts. These are NOT used in live trading.

## Structure

```
research/
├── optimizer/            ← Parameter optimization using Optuna
├── analysis/             ← Data analysis and universe building
│   ├── scripts/          ← Analysis scripts (generate universes, detect patterns)
│   └── outputs/          ← Generated CSV outputs (.gitignore)
├── database_analysis/    ← SQL analysis and data exploration
├── data_backfill/        ← Specialized backfill scripts (one-time use)
└── maintenance/          ← Diagnostics and data health checks
    └── diagnostics/      ← Debugging scripts (debug_arbe.py, etc.)
```

## Optimizer (`optimizer/`)

Bayesian optimization to find best trading parameters using Optuna.

### Key Scripts:
- `optuna_run.py` — Main Optuna optimization (run this to find best config)
- `meta_optimizer.py` — Meta-optimization (optimize the optimizer itself)
- `simulate_one.py` — Run a single trial
- `analyze.py` — Analyze optimization results

### Usage:
```bash
# Run 200 trials across a date range
python research/optimizer/optuna_run.py --start 2026-02-03 --end 2026-02-18 --trials 200

# Query best results
python research/optimizer/query_results.py
```

### Results:
Results are stored in SQLite databases in `optimizer/results.db`. View with:
```bash
optuna-dashboard sqlite:///research/optimizer/results.db
```

## Analysis (`analysis/`)

### Scripts (in `analysis/scripts/`):
- `build_gapper_universe.py` — Find all gap-up stocks over time
- `create_pillar23_universe.py` — Build curated universe from top gappers
- `generate_daily_gaprun_universe.py` — Daily gap-run candidates
- `compare_daily_universes.py` — Compare universe definitions
- `premarket_day_comparison.py` — Analyze premarket vs full-day patterns
- `generate_report.py` — Generate analysis reports

### Usage:
```bash
# Generate daily gaprun universe
python research/analysis/scripts/generate_daily_gaprun_universe.py

# Create pillar23 universe from historical data
python research/analysis/scripts/create_pillar23_universe.py
```

### Outputs (in `analysis/outputs/`):
Generated CSVs are stored here and are in `.gitignore`:
- `daily_gaprun_universe.csv` — Stocks that gapped up today
- `pillar23_universe.csv` — Curated list for backtesting
- `gapper_universe.csv` — All known gappers
- etc.

**NOTE**: These are regenerated on demand, not version-controlled.

## Database Analysis (`database_analysis/`)

SQL-based analysis scripts for data exploration and validation.

### Categories:

**Find & Analyze:**
- `find_gap_up_events.py` — Identify gap-up days
- `find_top_gappers_month.py` — Top gappers per month
- `find_best_simulation_windows.py` — Best date ranges for backtesting

**Analyze:**
- `analyze_gap_run_patterns.py` — Pattern analysis on gap-runs
- `analyze_pre_gap_features.py` — Features before gap-runs
- `analyze_single_day_coverage.py` — Data coverage audit

**Generate:**
- `generate_monthly_gaprun_top100_lists.py` — Monthly top-100 gappers
- `generate_true_top_gappers.py` — Merged top-gapper lists

**Sweep:**
- `sweep_prototype_prescreen.py` — Test prescreen thresholds
- `sweep_gapper_thresholds.py` — Optimize gapper filters
- `sweep_universe_thresholds.py` — Optimize universe filters

**Other:**
- `compare_prescreens.py` — Compare different filtering strategies
- `diagnose_data_coverage.py` — Check for data gaps
- `historical_tradable_stocks.py` — Build tradable stock history
- `prototype_prescreen_filters.py` — Test new filters
- `bootstrap_single_day_data.py` — One-time data setup
- `backfill_rel_vol_30d.py` — Build relative volume cache
- `build_rel_vol_cum_cache.py` — Cumulative volume cache
- `backfill_with_daily_stocks.py` — Legacy backfill

### Usage:
```bash
# Find gap-up events
python research/database_analysis/find_gap_up_events.py

# Analyze coverage for a date
python research/database_analysis/analyze_single_day_coverage.py --date 2026-02-13
```

## Data Backfill (`data_backfill/`)

Specialized one-time backfill scripts.

### Scripts:
- `backfill_gappers.py` — Backfill gap-run specific data
- `backfill_warmup.py` — Premarket warmup data

**NOTE**: These are archived here for reference. Core backfill (`backfill_optimized.py`) is in `production/data/backfill/`.

## Maintenance (`maintenance/`)

### Scripts (in `maintenance/`):
- `db_status.py` — Check database health
- `sanity_check.py` — Data validation
- `check_timezone.py` — Timezone verification

### Diagnostics (in `maintenance/diagnostics/`):
- `debug_arbe.py` — Debug entry gates for ARBE on a specific date
- `check_hour_data_coverage.py` — Check hourly bar coverage
- `check_tradable_stocks.py` — Check tradable symbol counts

## Workflow

### When optimizing parameters:
1. Run `research/optimizer/optuna_run.py` with new date ranges
2. Analyze results with `research/optimizer/analyze.py`
3. Once satisfied, extract best config and update `production/trading/` rules

### When analyzing data:
1. Use `research/database_analysis/` scripts to explore
2. Use `research/analysis/scripts/` to build universes
3. Generated outputs go to `research/analysis/outputs/` (not committed)

### When debugging:
1. Use scripts in `research/maintenance/diagnostics/`
2. Use `research/database_analysis/` for data exploration
3. Reference `archive/optunaDBfiles/README.md` for past optimization runs

## Notes

- These scripts are experimental and may change frequently
- No output is committed to git (CSVs are `.gitignore`d)
- Results databases are archived in `archive/optunaDBfiles/`
- Database files are in `.gitignore` (kept locally, not on GitHub)
