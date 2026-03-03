# Import Path Fixes Summary

Fixed import paths across all Python scripts after file reorganization. All imports now correctly reference the new directory structure.

## Files Fixed

### Data Collection & Backfill

**`data/backfill/backfill_optimized.py`**
- Line 22: Changed `sys.path.insert(0, '..'))` → `'../..'` (go up 2 levels to root)
- Line 550: Fixed STOCKS_FILE path: `'stocks_1_to_20.txt'` → `'../../database/stocks_1_to_20.txt'`
- Line 553: Updated script reference in error message

**`data/backfill/fill_gaps.py`**
- Line 23: Changed `sys.path.insert(0, '..'))` → `'../..'`
- Line 45: Fixed STOCKS_FILE path: `'stocks_1_to_20.txt'` → `'../../database/stocks_1_to_20.txt'`

**`data/collector/collect_data.py`**
- Line 18: Changed `sys.path.insert(0, '..'))` → `'../..'`
- Line 40: Fixed STOCKS_FILE path: `'stocks_1_to_20.txt'` → `'../../database/stocks_1_to_20.txt'`
- Line 13: Updated docstring usage example

### Backend API

**`backend/app.py`**
- Line 8: Changed `from scanner import` → `from backend.scanner import MomentumScanner`

**`backend/scanner.py`**
- Lines 1-5: Added sys.path setup for root import
- Line 6: Changed `from data_feed import` → `from backend.data_feed import`
- Line 7: Changed `from news_fetcher import` → `from backend.news_fetcher import`

**`backend/data_feed.py`**
- Lines 1-3: Added sys.path setup for root import

**`backend/news_fetcher.py`**
- No changes needed (imports Config inside __init__ method)

### Services

**`services/fetch_fundamentals.py`**
- Line 10: Updated docstring: `python database/` → `python services/`
- Line 38: Fixed STOCKS_FILE path: `'stocks_1_to_20.txt'` → `'../database/stocks_1_to_20.txt'`

**`services/fetch_stocks_1_to_20.py`**
- No changes needed (already correct)

### Simulator

**`simulator/simulate_date.py`**
- No changes needed (already correct)

**`simulator/simulate_date_range.py`**
- No changes needed (already correct)

**`simulator/simulation_engine.py`**
- No changes needed (already correct in previous work)

### Maintenance & Utils

**`maintenance/sanity_check.py`**
- No changes needed (already correct)

**`maintenance/db_status.py`**
- No changes needed (already correct)

**`maintenance/check_timezone.py`**
- No changes needed (already correct)

**`utils/query_helpers.py`**
- No changes needed (already correct)

**`utils/backtest_scanner.py`**
- No changes needed (already correct)

**`utils/trading_calendar.py`**
- No changes needed (created correct)

## Key Pattern

**For scripts in subdirectories:**
- Scripts in `data/backfill/`, `data/collector/`, `backend/`, `services/`, `maintenance/`, `simulator/` all use:
  ```python
  sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
  ```
  This goes up to the root where `config.py` lives.

**For file paths (stocks file is in database/):**
- From `data/backfill/`: `../../database/stocks_1_to_20.txt`
- From `data/collector/`: `../../database/stocks_1_to_20.txt`
- From `services/`: `../database/stocks_1_to_20.txt`

**For relative imports:**
- All imports use module names relative to root: `from backend.scanner import`, `from utils.query_helpers import`, etc.

## Testing

After fixes, all scripts should run without ModuleNotFoundError. Key test:
```bash
python data/backfill/backfill_optimized.py
```

Should now correctly:
1. Load Config from root
2. Find stocks_1_to_20.txt in database/ directory
3. Import any needed utilities from utils/ or other modules
