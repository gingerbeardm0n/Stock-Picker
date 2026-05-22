# Claude Code Instructions for Stock-Picker Project

**Last Updated**: March 3, 2026
**Status**: Active - Follow these rules for all work on this repo

---

## Primary Directive: File Organization

This project has a **dedicated codebase architect** that maintains folder structure. Before ANY agent creates files or folders, follow this protocol.

### Pre-Flight Checklist (REQUIRED Before Creating Files)

```
□ Is this file for LIVE TRADING code?
  YES → goes in production/<module>/
  NO  → continue to next question

□ Is this analysis/experiment/one-off work?
  YES → goes in research/<category>/
  NO  → continue to next question

□ Is this deprecated or historical?
  YES → goes in archive/
  NO  → ASK: Where should this go?
```

### Valid Locations (Do NOT Create Files Elsewhere)

#### Production Code (Live Trading)
- `production/trading/` — Entry/exit logic, patterns, indicators, models
- `production/simulator/` — Backtester (simulation_engine.py, simulate_date.py, simulate_date_range.py)
- `production/backend/` — Flask REST API, scanner, data feed
- `production/services/` — External APIs (Alpaca, Finnhub)
- `production/data/collector/` — Real-time data collection
- `production/data/backfill/` — Historical backfill (backfill_optimized.py, fill_gaps.py)
- `production/frontend/` — Web UI
- `production/utils/` — Helpers, trading calendar, query builders
- `production/tests/` — Unit tests
- `production/strategy/` — Trading strategy documentation
- `production/config.py` — Configuration (centralized)

#### Research Code (Analysis, Optimization, Experiments)
- `research/optimizer/` — Optuna parameter optimization (optuna_run.py, meta_optimizer.py, etc.)
- `research/analysis/scripts/` — Universe building, data analysis, report generation
- `research/analysis/outputs/` — Generated CSV files (add to .gitignore, keep locally)
- `research/database_analysis/` — SQL exploration, gap finding, pattern analysis
- `research/data_backfill/` — Specialized one-time backfill (backfill_gappers.py, etc.)
- `research/maintenance/` — Health checks, monitoring (db_status.py, sanity_check.py)
- `research/maintenance/diagnostics/` — Debug scripts (debug_arbe.py, check_*.py)

#### Archive (Old/Deprecated)
- `archive/` — Deprecated code, old approaches
- `archive/optunaDBfiles/` — Optimizer databases (62MB, for reference only, NOT in git)

#### Documentation
- `docs/` — Architecture, setup, design decisions
- Root-level: README.md, ROADMAP.md, QUICK_REFERENCE.md, FILE_PLACEMENT_GUIDE.md

---

## Rules (Strict)

### ✅ DO THIS

1. **Before creating ANY file**, check FILE_PLACEMENT_GUIDE.md
2. **Generated outputs** (CSV, JSON from analysis) → add to `.gitignore`, keep locally
3. **Database files** (.db) → add to `.gitignore`, keep locally
4. **Import paths** — Use sys.path.insert in entry points; check existing files for pattern
5. **Document** — Add comments explaining where files should go and why
6. **Ask first** — If unsure about location, ask before creating

### ❌ NEVER DO THIS

- Create `.py` files in root (except config.py which already exists)
- Commit generated CSV files to git (add to .gitignore instead)
- Create `.db` files without `.gitignore` entry
- Put research code in production or vice versa
- Create scripts without clear home/purpose
- Move files without updating import paths
- Ignore the checklist — ALWAYS follow it

---

## Workflow for Common Tasks

### Creating a New Trading Feature
1. **Add code to**: `production/trading/entry_engine.py` (or exit_engine.py, patterns.py, etc.)
2. **Add tests to**: `production/tests/test_<feature>.py`
3. **No analysis CSV files** — all logic stays in production/

### Running Parameter Optimization
1. **File location**: `research/optimizer/optuna_run.py`
2. **Output location**: `research/optimizer/results.db` (add to .gitignore)
3. **CSV analysis**: Save to `research/analysis/outputs/` (add to .gitignore)
4. **Don't commit**: results.db or any CSV outputs

### Building Universe Analysis
1. **Script location**: `research/analysis/scripts/build_<name>.py`
2. **Output location**: `research/analysis/outputs/<name>.csv`
3. **Add to .gitignore**: `research/analysis/outputs/*.csv`
4. **Locally**: Keep CSV for reference, don't commit to git

### Creating Debug/Diagnostic Scripts
1. **Location**: `research/maintenance/diagnostics/debug_<name>.py`
2. **Purpose**: One-off debugging, exploration (not part of live trading)
3. **Example**: `debug_arbe.py` traces entry gates for a symbol

### Backfilling Data
1. **Core backfill**: `production/data/backfill/backfill_optimized.py` (used live)
2. **Specialized**: `research/data_backfill/backfill_gappers.py` (one-time use)
3. **Real-time collection**: `production/data/collector/collect_data.py`

---

## Import Patterns (Follow These)

### Production Entry Points (Add to sys.path)
```python
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Now can import modules:
from trading.entry_engine import evaluate_entry
from simulator.simulation_engine import SimulationRunner
from config import Config
```

### Research Code (Import from Both)
```python
import sys
import os
# Add both research/ and production/ to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))  # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

# Now can import from both:
from optimizer.simulate_one import run_date_range
from trading.models import ScannerConfig
from simulator.simulation_engine import SimulationRunner
```

---

## Git Rules

### What Gets Committed
- ✅ Python code (.py files)
- ✅ Documentation (.md files)
- ✅ Strategy files (UTS_*.md)
- ✅ .gitignore (updated rules)
- ✅ requirements.txt

### What Does NOT Get Committed
- ❌ .db files (databases — add to .gitignore)
- ❌ .csv files (generated outputs — add to .gitignore)
- ❌ .env (secrets — already in .gitignore)
- ❌ .venv/ (dependencies — already in .gitignore)
- ❌ __pycache__/ (compiled — already in .gitignore)

### Adding to .gitignore
When creating a new type of output file:
```gitignore
# New output type (keep locally, don't commit)
research/new_analysis/*.csv     # Generated outputs
research/new_analysis/cache/    # Cache files
```

---

## Questions?

- **Where should this file go?** → Read `FILE_PLACEMENT_GUIDE.md`
- **How do I run this?** → Check `QUICK_REFERENCE.md`
- **What's the folder structure?** → See `production/README.md` and `research/README.md`
- **What are the organization rules?** → This file (CLAUDE.md)

---

## Enforcement

- **All agents must follow these rules**
- **Codebase architect reviews new files/folders**
- **Violations should be caught before commit**
- **If unsure, ask — don't guess**

---

## Recent Changes (Reorganization - Mar 3, 2026)

- Moved all production code to `production/`
- Moved all research/analysis to `research/`
- Archived 11 .db files to `archive/optunaDBfiles/` (not in git)
- Created decision tree in `FILE_PLACEMENT_GUIDE.md`
- All imports tested and working ✓

See `REORGANIZATION_COMPLETE.md` for full details.
