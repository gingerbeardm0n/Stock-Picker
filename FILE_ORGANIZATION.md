# File Organization

## Directory Structure

The project is organized into logical modules by function:

```
Stock-Picker/
├── config.py                              # Global configuration
├── backend/                               # Live trading API & scanner
│   ├── app.py                            # Flask web app
│   ├── scanner.py                        # Live scanner
│   ├── data_feed.py                      # Alpaca data feed
│   └── news_fetcher.py                   # News aggregator
│
├── frontend/                              # Web UI (JavaScript/HTML)
│
├── simulator/                             # Backtesting engine (NEW)
│   ├── simulation_engine.py              # Core simulation logic
│   ├── simulate_date.py                  # Single-day backtester
│   └── simulate_date_range.py            # Multi-day backtester
│
├── data/                                  # Market data collection & processing (NEW)
│   ├── collector/                        # Live data collection
│   │   └── collect_data.py               # Alpaca minute-bar collector
│   └── backfill/                         # Historical data recovery
│       ├── backfill_optimized.py         # Bulk historical backfill
│       └── fill_gaps.py                  # Gap recovery (detects downtime)
│
├── services/                              # One-off utilities & API integrations (NEW)
│   ├── fetch_fundamentals.py             # Company data (float, market cap)
│   └── fetch_stocks_1_to_20.py           # Snapshot of top movers
│
├── maintenance/                           # Admin & health check tools (NEW)
│   ├── db_status.py                      # Database coverage report
│   ├── sanity_check.py                   # Scanner validation
│   └── check_timezone.py                 # Timezone verification
│
├── utils/                                 # Shared utilities (NEW)
│   ├── query_helpers.py                  # Database query layer
│   ├── trading_calendar.py               # NYSE holiday calendar
│   └── backtest_scanner.py               # Scanner logic for backtesting
│
├── strategy/                              # Trading strategy documentation
│
└── archive/                               # Legacy code (not used)
```

## Migration Notes (Feb 20, 2026)

**Before**: All scripts were in `database/` folder, making it hard to understand what each does.

**After**: Scripts organized by purpose:
- **Simulator** — Backtesting/paper trading logic
- **Data** — Collecting, backfilling, maintaining market data
- **Services** — External API integrations (Finnhub, Alpaca snapshots)
- **Utils** — Shared code (database queries, calendar, scanner logic)
- **Maintenance** — Admin tools (health checks, validation, debugging)

## Running Scripts

All scripts expect to be run from the project root:

```bash
# Simulator
python simulator/simulate_date.py --date 2026-02-13
python simulator/simulate_date_range.py --start 2026-02-10 --end 2026-02-18

# Data management
python data/collector/collect_data.py  # runs continuously
python data/backfill/fill_gaps.py 2026-02-19
python data/backfill/backfill_optimized.py --start 2026-02-01 --end 2026-02-18

# Services
python services/fetch_fundamentals.py
python services/fetch_stocks_1_to_20.py

# Maintenance
python maintenance/db_status.py
python maintenance/sanity_check.py 2026-02-13
python maintenance/check_timezone.py
```

## Import Paths

Files use absolute imports from project root (possible due to `sys.path` manipulation):

```python
from utils.query_helpers import StockDataDB
from simulator.simulation_engine import SimulationRunner
from utils.trading_calendar import get_trading_days
from utils.backtest_scanner import backtest_single_day
```

All Python packages have `__init__.py` files to enable proper module resolution.
