# Quick Reference: Old vs New Paths

## Entry Points (For Running)

### Simulation
```bash
# OLD (no longer works):
python simulator/simulate_date_range.py

# NEW:
python production/simulator/simulate_date_range.py --start 2026-02-03 --end 2026-02-18
```

### Live Trading Backend
```bash
# OLD:
python backend/app.py

# NEW:
python production/backend/app.py
```

### Fetch Fundamentals
```bash
# OLD:
python services/fetch_fundamentals.py

# NEW:
python production/services/fetch_fundamentals.py
```

### Collect Real-Time Data
```bash
# OLD:
python data/collector/collect_data.py

# NEW:
python production/data/collector/collect_data.py
```

### Historical Backfill
```bash
# OLD:
python data/backfill/backfill_optimized.py

# NEW:
python production/data/backfill/backfill_optimized.py
```

### Parameter Optimization
```bash
# OLD:
python optimizer/optuna_run.py --trials 200

# NEW:
python research/optimizer/optuna_run.py --trials 200
```

---

## Module Imports (For Development)

### If Adding Code to Production

#### Entry/Exit Logic
```python
# Add to: production/trading/entry_engine.py or production/trading/exit_engine.py
from trading.models import EntrySignal, ExitSignal
from trading.indicators import get_current_ema
```

#### Simulation
```python
# Add to: production/simulator/
from simulator.simulation_engine import SimulationRunner
from utils.trading_calendar import get_trading_days
```

#### Backend
```python
# Add to: production/backend/
from backend.scanner import MomentumScanner
from services.fetch_fundamentals import fetch_float_market_cap
```

### If Running Analysis

#### Database Analysis
```bash
# Run from: research/database_analysis/
python research/database_analysis/find_gap_up_events.py
python research/database_analysis/analyze_gap_run_patterns.py
```

#### Optimizer
```bash
# Run from: research/optimizer/
python research/optimizer/optuna_run.py
python research/optimizer/analyze.py
```

#### Universe Building
```bash
# Run from: research/analysis/scripts/
python research/analysis/scripts/build_gapper_universe.py
python research/analysis/scripts/create_pillar23_universe.py
```

---

## Configuration

```bash
# Config file (unchanged):
production/config.py

# Environment secrets:
.env  (not committed, add to this)

# Example .env:
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
FINNHUB_API_KEY=your_key
DB_HOST=localhost
```

---

## Documentation

| Topic | Location |
|-------|----------|
| Production setup & running | `production/README.md` |
| Research/optimization setup | `research/README.md` |
| Archived databases | `archive/optunaDBfiles/README.md` |
| Trading strategy | `production/strategy/UTS_*.md` |
| This reorganization | `REORGANIZATION_COMPLETE.md` |
| Original detailed plan | `REORGANIZATION_PLAN.md` |

---

## Git Status

After reorganization, you should:

```bash
# Check what was moved
git status

# Stage everything
git add -A

# Commit
git commit -m "Reorganize: separate production and research code"

# Nothing about the databases should be in the commit
# (they're in .gitignore now)
```

---

## File Locations Summary

### Core Trading System (Production)

| What | Old | New |
|------|-----|-----|
| Entry logic | `trading/entry_engine.py` | `production/trading/entry_engine.py` |
| Exit logic | `trading/exit_engine.py` | `production/trading/exit_engine.py` |
| Patterns | `trading/patterns.py` | `production/trading/patterns.py` |
| Indicators | `trading/indicators.py` | `production/trading/indicators.py` |
| Data models | `trading/models.py` | `production/trading/models.py` |
| Portfolio mgmt | `trading/portfolio_manager.py` | `production/trading/portfolio_manager.py` |

### Simulation (Production)

| What | Old | New |
|------|-----|-----|
| Engine | `simulator/simulation_engine.py` | `production/simulator/simulation_engine.py` |
| Single day | `simulator/simulate_date.py` | `production/simulator/simulate_date.py` |
| Multi-day | `simulator/simulate_date_range.py` | `production/simulator/simulate_date_range.py` |

### Data Pipeline (Production)

| What | Old | New |
|------|-----|-----|
| Real-time collection | `data/collector/collect_data.py` | `production/data/collector/collect_data.py` |
| Historical backfill | `data/backfill/backfill_optimized.py` | `production/data/backfill/backfill_optimized.py` |
| Gap fill | `data/backfill/fill_gaps.py` | `production/data/backfill/fill_gaps.py` |
| Gapper backfill | `data/backfill/backfill_gappers.py` | `research/data_backfill/backfill_gappers.py` |
| Warmup backfill | `data/backfill/backfill_warmup.py` | `research/data_backfill/backfill_warmup.py` |

### Analysis & Optimization (Research)

| What | Old | New |
|------|-----|-----|
| Optuna optimization | `optimizer/*.py` | `research/optimizer/*.py` |
| Database analysis | `database/*.py` | `research/database_analysis/*.py` |
| Universe building | `analysis/*.py` | `research/analysis/scripts/*.py` |
| Diagnostics | `debug_arbe.py`, `check_*.py` | `research/maintenance/diagnostics/` |
| Health checks | `maintenance/*.py` | `research/maintenance/` |

### Archived (Safety Backup)

| What | Location | Size |
|------|----------|------|
| Optimizer databases | `archive/optunaDBfiles/` | 62M |
| Old deprecated code | `archive/` | Unchanged |

---

## Imports in Code (Examples)

### Production code (simulator, backend, etc.)

All add the parent directory to sys.path, so use relative imports:

```python
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from trading.entry_engine import evaluate_entry      # works ✓
from simulator.simulation_engine import SimulationRunner  # works ✓
from config import Config                            # works ✓
```

### Research code (optimizer, analysis, etc.)

Add both research/ and production/ to path:

```python
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))          # research/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../production')))  # production/

from optimizer.simulate_one import run_date_range    # works ✓
from trading.models import ScannerConfig              # works ✓
```

---

## Common Tasks

### Run a single-day backtest
```bash
cd /c/Repositories/Stock-Picker
python production/simulator/simulate_date.py --date 2026-02-13
```

### Run multi-day backtest
```bash
python production/simulator/simulate_date_range.py --start 2026-02-03 --end 2026-02-18 --account 5000 --risk 2.0
```

### Start live trading backend
```bash
python production/backend/app.py
# Then open http://localhost:5000 in browser
```

### Optimize parameters
```bash
python research/optimizer/optuna_run.py --start 2026-02-03 --end 2026-02-18 --trials 200
```

### Build universe
```bash
python research/analysis/scripts/create_pillar23_universe.py
# Output: research/analysis/outputs/pillar23_universe.csv
```

### Backfill historical data for a symbol universe
```bash
python production/data/backfill/backfill_optimized.py
```

---

## Did the Reorganization Break Anything?

✅ **NO** — All entry points tested and working:
- Simulator imports: ✓
- Backend imports: ✓
- Optimizer imports: ✓
- All production code working: ✓

Just remember: **Always run from the repo root** with `python production/...` or `python research/...` paths.
