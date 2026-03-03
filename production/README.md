# Production Code

This folder contains everything needed for live trading.

## Structure

```
production/
├── trading/              ← Trading logic (entry, exit, patterns, indicators, models, portfolio management)
├── simulator/            ← Backtesting engine (simulate_date.py, simulate_date_range.py, simulation_engine.py)
├── backend/              ← Flask REST API (app.py, scanner.py, data_feed.py, news_fetcher.py)
├── services/             ← External API integrations (Alpaca, Finnhub)
├── data/
│   ├── collector/        ← Real-time data collection (collect_data.py)
│   └── backfill/         ← Historical data backfill (backfill_optimized.py, fill_gaps.py)
├── frontend/             ← Web UI (index.html, app.js, style.css)
├── utils/                ← Helpers (trading_calendar, query_helpers, backtest_scanner)
├── tests/                ← Unit tests
├── strategy/             ← Trading strategy documentation
├── config.py             ← Main configuration file
└── requirements.txt      ← Python dependencies
```

## Entry Points

### For Simulation/Backtesting:
```bash
# Single day backtest
python production/simulator/simulate_date.py --date 2026-02-13

# Multi-day backtest
python production/simulator/simulate_date_range.py --start 2026-02-03 --end 2026-02-18

# With custom parameters
python production/simulator/simulate_date_range.py --account 5000 --risk 2.0
```

### For Live Trading (Backend):
```bash
# Start the Flask server
python production/backend/app.py
```

### For Data Collection:
```bash
# Continuous real-time collection (runs 4am-8pm ET)
python production/data/collector/collect_data.py

# Backfill historical data
python production/data/backfill/backfill_optimized.py
```

### For Fundamentals:
```bash
# Fetch float and market cap from Finnhub
python production/services/fetch_fundamentals.py
```

## Core Modules

### `trading/` — Entry/Exit Logic
- `entry_engine.py` — Checks Ross Cameron's 5 pillars + technical patterns
- `exit_engine.py` — Manages profit taking, stops, trailing stops
- `patterns.py` — Pattern detection (Bull Flag, ABCD, Flat Top, etc.)
- `indicators.py` — EMA-9, MACD, volume direction, relative volume
- `models.py` — Data classes (PatternSignal, EntrySignal, ExitSignal, etc.)
- `portfolio_manager.py` — Capital management and risk rules

### `simulator/` — Backtesting
- `simulation_engine.py` — Core time-forward engine, minute-by-minute execution
- `simulate_date.py` — CLI for single-day simulation
- `simulate_date_range.py` — CLI for multi-day simulation with aggregation

### `backend/` — REST API
- `app.py` — Flask server, routes for scanner/trades
- `scanner.py` — Real-time scanner logic
- `data_feed.py` — Market data streaming
- `news_fetcher.py` — News catalyst fetching

### `services/` — External APIs
- `fetch_fundamentals.py` — Fetch float/market cap from Finnhub
- `fetch_stocks_1_to_20.py` — Initial stock universe setup
- `fetch_stocks_in_price_range.py` — Backfill universe for historical analysis

### `data/` — Data Management
- `collector/collect_data.py` — Continuous 1-minute bar collection from Alpaca
- `backfill/backfill_optimized.py` — Bulk historical backfill to TimescaleDB
- `backfill/fill_gaps.py` — Detect and fill data collection gaps

## Configuration

All settings live in `config.py`:
```python
DB_HOST = 'localhost'
DB_PORT = 5432
DB_NAME = 'stock_picker'
ALPACA_API_KEY = os.getenv('ALPACA_API_KEY')
FINNHUB_API_KEY = os.getenv('FINNHUB_API_KEY')
```

Secrets go in `.env` (not committed).

## Testing

```bash
pytest production/tests/ -v
```

## Deployment

To containerize or deploy:
1. This entire `production/` folder is self-contained
2. Dependencies: `pip install -r production/requirements.txt`
3. Database: Requires TimescaleDB connection (see `config.py`)
4. Environment: Set `.env` with API keys

## Documentation

See `production/strategy/` for detailed trading rules and strategy documentation.
