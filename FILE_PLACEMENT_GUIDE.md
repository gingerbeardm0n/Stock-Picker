# File Placement Decision Tree

**Use this guide BEFORE creating any new file.** Answer the questions in order to find the right location.

---

## Quick Decision Tree

```
START: You're creating a new file

  ↓ Q1: What TYPE of file?
  ├─ Python code (.py) ...................... → Go to Q2
  ├─ Data/CSV output (.csv) ................ → Go to DATA
  ├─ Documentation (.md) ................... → Go to DOCS
  ├─ Database file (.db, .sql) ............. → Go to DB
  └─ Other (config, JSON, etc.) ........... → Go to OTHER

  ┌─────────────────────────────────────────┐
  │ Q2: Is this code for LIVE TRADING?     │
  │ (i.e., will it run in production?)     │
  └─────────────────────────────────────────┘

  YES → PRODUCTION (see below)
  NO  → RESEARCH (see below)
  UNSURE → Ask: "If I deploy this, will it be running?"
```

---

## PRODUCTION Code (Live Trading)

**These files are used in real-time trading, simulation, or data collection.**

### Entry/Exit Logic
```
File type: trading rule, pattern, indicator, or signal logic
Location: production/trading/

Examples:
  production/trading/entry_engine.py     ← Entry decision logic
  production/trading/exit_engine.py      ← Exit signal logic
  production/trading/patterns.py         ← Pattern detection (Bull Flag, ABCD, etc.)
  production/trading/indicators.py       ← EMA, MACD, volume calculations
  production/trading/models.py           ← Data classes (PatternSignal, EntrySignal, etc.)
  production/trading/portfolio_manager.py ← Capital/position management
```

### Simulation (Backtesting)
```
File type: backtester, historical simulator, or testing harness
Location: production/simulator/

Examples:
  production/simulator/simulation_engine.py   ← Core backtester
  production/simulator/simulate_date.py       ← CLI for single day
  production/simulator/simulate_date_range.py ← CLI for multi-day
```

### REST API / Web Backend
```
File type: Flask routes, data feeds, API endpoints
Location: production/backend/

Examples:
  production/backend/app.py          ← Main Flask app
  production/backend/scanner.py      ← Real-time scanner
  production/backend/data_feed.py    ← Live market data streaming
  production/backend/news_fetcher.py ← News catalyst fetching
```

### External API Integrations
```
File type: Alpaca API client, Finnhub API, data fetching
Location: production/services/

Examples:
  production/services/fetch_fundamentals.py    ← Finnhub float/market cap
  production/services/fetch_stocks_1_to_20.py  ← Initial universe setup
  production/services/fetch_stocks_in_price_range.py ← Historical backfill helper
```

### Data Collection
```
File type: real-time data collection, live bar aggregation
Location: production/data/collector/

Examples:
  production/data/collector/collect_data.py ← Alpaca bar collection (4am-8pm ET)
```

### Backfill & Gap Filling
```
File type: historical data backfill, gap detection
Location: production/data/backfill/

Examples:
  production/data/backfill/backfill_optimized.py ← Bulk historical load
  production/data/backfill/fill_gaps.py          ← Gap detection/filling

NOT here:
  - One-time backfills → research/data_backfill/
  - Specialized fills → research/data_backfill/
```

### Frontend
```
File type: HTML, JavaScript, CSS for web UI
Location: production/frontend/

Examples:
  production/frontend/index.html  ← Main page
  production/frontend/app.js      ← AG Grid table logic
  production/frontend/style.css   ← Styling
```

### Utilities (Helpers)
```
File type: shared helpers, trading calendar, SQL query builders
Location: production/utils/

Examples:
  production/utils/trading_calendar.py ← NYSE trading day logic
  production/utils/query_helpers.py    ← TimescaleDB query wrappers
  production/utils/backtest_scanner.py ← Scanner batch queries
```

### Unit Tests
```
File type: pytest tests for production code
Location: production/tests/

Examples:
  production/tests/test_entry_engine.py
  production/tests/test_indicators.py
  production/tests/test_patterns.py
```

### Strategy Documentation
```
File type: trading rules, entry/exit patterns, risk management docs
Location: production/strategy/

Examples:
  production/strategy/UTS_OVERVIEW.md
  production/strategy/UTS_ENTRY_RULES.md
  production/strategy/UTS_EXIT_RULES.md
  production/strategy/UTS_RISK_MANAGEMENT.md
  production/strategy/UTS_PSYCHOLOGY.md
```

### Configuration
```
File type: centralized settings, API keys, database config
Location: production/config.py

Note: Only ONE config.py file exists. Update it, don't create new files.
```

---

## RESEARCH Code (Analysis & Experiments)

**These files are used for analysis, parameter tuning, and one-off investigations.**

### Parameter Optimization
```
File type: Optuna trials, parameter sweeps, meta-optimization
Location: research/optimizer/

Examples:
  research/optimizer/optuna_run.py      ← Main Optuna optimization
  research/optimizer/meta_optimizer.py  ← ML-guided optimization
  research/optimizer/simulate_one.py    ← Run single trial
  research/optimizer/run_config.py      ← Parameter configuration
  research/optimizer/analyze.py         ← Analyze results
  research/optimizer/query_results.py   ← Query results database
```

### Universe Building
```
File type: find stocks, build gapper lists, analyze universes
Location: research/analysis/scripts/

Examples:
  research/analysis/scripts/build_gapper_universe.py
  research/analysis/scripts/create_pillar23_universe.py
  research/analysis/scripts/generate_daily_gaprun_universe.py
  research/analysis/scripts/compare_daily_universes.py
  research/analysis/scripts/premarket_day_comparison.py
```

### Database Exploration
```
File type: find patterns, analyze data, diagnose coverage
Location: research/database_analysis/

Examples:
  research/database_analysis/find_gap_up_events.py       ← Find gaps
  research/database_analysis/find_top_gappers_month.py   ← Top gappers
  research/database_analysis/analyze_gap_run_patterns.py ← Pattern analysis
  research/database_analysis/analyze_pre_gap_features.py ← Pre-gap features
  research/database_analysis/analyze_single_day_coverage.py ← Coverage audit
  research/database_analysis/generate_daily_gaprun_universe.py ← Daily lists
  research/database_analysis/sweep_gapper_thresholds.py ← Threshold tuning
  research/database_analysis/prototype_prescreen_filters.py ← Filter testing
  research/database_analysis/diagnose_data_coverage.py ← Data health
```

### One-Time Backfills
```
File type: specialized backfill, gapper-only fills, warmup data
Location: research/data_backfill/

Examples:
  research/data_backfill/backfill_gappers.py ← Gap-run specific backfill
  research/data_backfill/backfill_warmup.py  ← Premarket warmup load
```

### Maintenance & Diagnostics
```
File type: health checks, database status, debug traces
Location: research/maintenance/ or research/maintenance/diagnostics/

Examples:
  research/maintenance/db_status.py ← Check TimescaleDB health
  research/maintenance/sanity_check.py ← Data validation
  research/maintenance/check_timezone.py ← TZ verification

  research/maintenance/diagnostics/debug_arbe.py ← Trace entry gates for symbol
  research/maintenance/diagnostics/check_hour_data_coverage.py ← Hourly bar audit
  research/maintenance/diagnostics/check_tradable_stocks.py ← Symbol counts
```

---

## DATA Files (Generated Outputs)

**Do NOT commit these to git. Add to `.gitignore`. Keep locally for reference.**

### Generated CSVs
```
Location: research/analysis/outputs/

Examples:
  research/analysis/outputs/daily_gaprun_universe.csv
  research/analysis/outputs/pillar23_universe.csv
  research/analysis/outputs/premarket_day_features.csv
  research/analysis/outputs/universe_comparison.csv

.gitignore entry:
  research/analysis/outputs/*.csv
```

### Optimizer Output CSVs
```
Location: research/optimizer/

Examples:
  research/optimizer/*.csv (any analysis CSV from optimization)

.gitignore entry:
  research/optimizer/*.csv
```

### Cache Files
```
Location: Any /cache/ subfolder

.gitignore entries:
  data/cache/
  research/optimizer/logs/
  production/__pycache__/
  research/__pycache__/
```

---

## DOCUMENTATION Files

```
Location: docs/ or root-level

Root-level docs:
  README.md                      ← Project overview
  ROADMAP.md                     ← Development roadmap
  QUICK_REFERENCE.md             ← Old vs new paths, CLI commands
  FILE_PLACEMENT_GUIDE.md        ← This file
  REORGANIZATION_COMPLETE.md     ← Reorganization summary (historical)

Module READMEs:
  production/README.md           ← How to run production code
  research/README.md             ← How to run research/analysis
  archive/README.md              ← Archive explanation
  archive/optunaDBfiles/README.md ← Database backup info

Settings/Guidelines:
  .claude/CLAUDE.md              ← Rules for all agents (this project)
  .claude/keybindings.json       ← IDE keybindings
  .claude/settings.json          ← Claude Code settings
```

---

## DATABASE Files (.db, .sql)

```
RULE: Add to .gitignore, keep locally ONLY

Archived databases (for reference, not live):
  archive/optunaDBfiles/pillar23_results.db    ← Main optimization results
  archive/optunaDBfiles/pillar23_optuna.db     ← Trial metadata
  archive/optunaDBfiles/robust_results.db      ← Old full-year run
  archive/optunaDBfiles/optuna.db              ← Early experiments
  ...etc (9 more, see README)

.gitignore entries:
  archive/optunaDBfiles/
  research/optimizer/*.db
  research/optimizer/results.db
```

SQL Schema Files:
```
Location: research/database_analysis/ (not schema files, just exploratory SQL)

Examples:
  research/database_analysis/create_sandbox_candle_tables.sql
  research/database_analysis/add_rel_vol_column.sql
```

---

## OTHER Files

```
Config Files:
  production/config.py ← Main centralized config (only ONE)
  .env ← Secrets (not committed, already in .gitignore)
  requirements.txt ← Python dependencies
  pyproject.toml ← (if using modern Python packaging)

Hidden/System:
  .gitignore ← Ignored files rules
  .github/ ← GitHub workflows (if any)
  .claude/ ← Claude Code settings
```

---

## Common Mistakes (Don't Do These!)

### ❌ Wrong: Creating root-level Python files
```python
# NO:
./my_script.py          ← Don't create here

# YES:
production/my_module.py       ← If it's production
research/analysis/scripts/my_script.py ← If it's analysis
```

### ❌ Wrong: Committing CSV outputs
```
# NO - This is in git:
analysis/daily_gaprun_universe.csv   ← WRONG, bloats repo

# YES - Add to .gitignore, keep locally:
research/analysis/outputs/daily_gaprun_universe.csv
# And add: research/analysis/outputs/*.csv to .gitignore
```

### ❌ Wrong: Mixing production and research
```python
# NO - Research code importing production directly:
import simulator  # from root

# YES - Use sys.path.insert:
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))
from simulator.simulation_engine import SimulationRunner
```

### ❌ Wrong: Database files in git
```
# NO - This is in git:
optimizer/pillar23_results.db  ← WRONG, 44MB bloats repo

# YES - Add to .gitignore, keep locally:
archive/optunaDBfiles/pillar23_results.db
# And add: archive/optunaDBfiles/ to .gitignore
```

---

## Decision Tree - Quick Version

```
Creating a file?

1. What is it?
   - Trading logic? → production/trading/
   - Backtester? → production/simulator/
   - API backend? → production/backend/
   - Data collection? → production/data/collector/
   - Backfill? → production/data/backfill/ (live) or research/data_backfill/ (one-time)
   - External API? → production/services/
   - Tests? → production/tests/
   - Docs? → production/strategy/ or docs/
   - Settings? → production/config.py

   - Optimization? → research/optimizer/
   - Universe building? → research/analysis/scripts/
   - Data exploration? → research/database_analysis/
   - Debug/diagnostic? → research/maintenance/diagnostics/
   - Health check? → research/maintenance/

   - Generated data? → .gitignore + research/analysis/outputs/
   - Database file? → .gitignore + archive/optunaDBfiles/
   - Documentation? → docs/ or root-level

2. If still unsure → Check existing similar files or ask!
```

---

## Still Stuck?

- **Find similar files** — Look at what already exists in that location
- **Check the READMEs** — `production/README.md`, `research/README.md`, `.claude/CLAUDE.md`
- **Ask before creating** — Better to ask than create in the wrong place and have to move it

---

## Last Updated
March 3, 2026 — After repository reorganization
