# Stock Scanner — Master Roadmap

## Architecture Overview

```
Alpaca API (data feed)
    |
    v
collect_data.py  ──────►  TimescaleDB (PostgreSQL)
                           ├── stock_candles_1m  (minute bars, 4am-8pm ET)
                           ├── stock_candles_1d  (daily bars)
                           └── stock_fundamentals (float, market cap from Finnhub)
                                     |
                                     v
                           backtest_scanner.py  (filtering engine)
                                     |
                                     v
                           backend/app.py  (Flask API)
                                     |
                                     v
                           frontend/  (AG Grid UI)
```

---

## Phase 1: Core Scanner — COMPLETE ✅

### Data Infrastructure
- [x] TimescaleDB setup with hypertable chunking
- [x] `collect_data.py` — continuous minute bar collection, 4am-8pm ET
- [x] `backfill_optimized.py` — bulk historical backfill (Feb 3-18, 3.15M bars)
- [x] `database/stocks_1_to_20.txt` — ~4,000 stock universe ($1-$20 range)
- [x] `fetch_fundamentals.py` — float + market cap from Finnhub (~4,000 stocks)

### Ross Cameron's 5 Pillars (all implemented)
- [x] **Pillar 1**: Price $2-$20
- [x] **Pillar 2**: % Change 10%+ (from prior close)
- [x] **Pillar 3**: Relative Volume 5x+ (correct time-of-day comparison)
- [x] **Pillar 4**: Float < 20M shares (from Finnhub fundamentals)
- [x] **Pillar 5**: News catalyst (from news fetcher)
- [x] **Bonus**: Market cap < $500M, Spread < $0.15

### Scanner Engine
- [x] `backtest_scanner.py` — batch query optimization (4 DB queries for all stocks)
- [x] Relative volume fixed: `(volume today) / (avg volume at same time historically)`
- [x] Premarket gain calculated from prior day close
- [x] Float/market cap filters with graceful degradation (pass if no data)
- [x] Live spread enrichment from Alpaca snapshots (live mode only)
- [x] Failure reason logging + breakdown summary

### Flask API
- [x] `POST /api/scan/database` — live and backtest scanning
- [x] `POST /api/criteria` — update filter criteria from UI
- [x] Criteria sync: UI → `Config.SCANNER_CRITERIA` → `backtest_scanner.CRITERIA`
- [x] Key mapping: `min_premarket_volume` → `min_morning_volume`, etc.

### Frontend UI
- [x] AG Grid table with sorting/filtering
- [x] Live Mode / Backtest Mode toggle
- [x] Backtest date + time picker
- [x] Filter checkboxes (toggle each criterion on/off)
- [x] "Scan Now" button always saves current filter state before scanning
- [x] News modal popup per stock

### Validation
- [x] `sanity_check.py` — compares scanner results vs raw DB ground truth
  - Feb 13 test: MLEC (+69%, 1415x) correctly caught
  - Feb 17 test: 5 stocks (VHUB 28.5x, IBG 18.7x, RSI 9.0x, QMCO 6.5x, VVPR 6.0x) ✅

---

## Phase 2: Simulation Engine — MVP COMPLETE ✅

### Goal: Validate strategy with minute-by-minute paper trading

Build a discrete event simulator that feeds historical data one minute at a time (no lookahead) and executes trading logic at CPU speed. Enables rapid iteration on entry/exit rules before 60-day backfill completes.

### Completed
- [x] **PositionManager** (`simulation_engine.py`)
  - Track open positions, entry price, shares, stop loss, profit targets
  - Calculate position size based on risk rules
  - Manage scaling (50% at 2:1, 25% at 3:1, trailing stops)
  - Log all trades with entry/exit reasons

- [x] **SimulationRunner** (`simulation_engine.py`)
  - Load minute bars for date (4am-12pm ET, no lookahead)
  - Process each minute sequentially
  - Evaluate entry/exit signals
  - Update account balance with realized P&L

- [x] **CLI Interfaces**
  - `simulate_date.py` — run single day simulation
  - `simulate_date_range.py` — run multi-day aggregation + statistics

### MVP Test Results (Feb 3-18, 11 trading days)
**With Simple Volume-Based Scanner**:
- ✅ 25 total trades executed
- ✅ System profitable: **+$3,635 total** (avg +$330/day)
- ✅ Position management working: scaling, stops, targets all executed correctly
- ⚠️ Win rate only 19.7% (expected for simple filtering)
- Key insight: Works well despite low win rate (big winners offset losses)

**With Real 5-Pillar Scanner (BEFORE FIX)**:
- ❌ 12 total trades
- ❌ System LOSING: **-$1,129 total** (avg -$103/day)
- ❌ Win rate only 7.6%
- 🚨 **ROOT CAUSE IDENTIFIED**: Minute bar data missing critical premarket window!
  - Current data starts at ~09:28 EST (14:28 UTC), should start at 04:00 EST (09:00 UTC)
  - All big Ross Cameron gaps/runners happen 4am-9:30am; we're entering too late
  - Impact: Filters are correctly rejecting mediocre setups, but we're missing the A+ ones

### Immediate Next Tasks
1. **Integrate real scanner logic** (highest priority)
   - Replace simple volume ranking with 5-pillar evaluation
   - Proper relative volume calculation (time-of-day adjusted)
   - Float/market cap/spread filters
   - **Target impact**: Win rate should improve to 50%+

2. **Add technical exit signals**
   - EMA-9 close below price
   - Volume dry-up detection
   - Time-of-day decay (after 11 AM)

3. **Per-pattern analysis**
   - Identify which entry patterns work best
   - Rank by success rate

4. **Time-of-day statistics**
   - Measure win rate by hour
   - Identify peak profitability window

### Data Requirements
- [x] We have Feb 3-18 data (2+ weeks) — MVP testing complete
- [ ] Will scale to 60-day data range after backfill completes

---

## Phase 2.5: Live Validation & Tuning (After Simulator Built)

### Immediate Next Steps
- [ ] **Simulator-assisted live test** during market hours
  - Run live scanner at 9:15 AM, capture results
  - Simulate same day retroactively with simulator
  - Compare: "What would simulator have done?" vs "What did live market do?"
  - Use to tune entry/exit thresholds

- [ ] **Multi-week simulation** across all collected dates (Feb 3-18)
  - Run `simulate_date_range(Feb 3, Feb 18)`
  - Measure: daily win rate, profit factor, best/worst times
  - Identify patterns that work

### Known Limitations to Address
- [ ] **Relative volume accuracy**: Only 2 weeks of premarket data (4am bars)
  - Historical data collected from 4am now — need 20+ days to have reliable time-of-day averages
  - Re-evaluate quality around March 3+ (3 weeks of 4am data)
- [ ] **`min_avg_volume` not UI-controllable**: Hardcoded at 500K, no checkbox in UI
  - Consider adding it to the criteria form
- [ ] **Market cap filter blocks stocks without Finnhub data**: ~900 stocks not fetched yet
  - Run `fetch_fundamentals.py` again for new stocks added since initial run
- [ ] **Float data freshness**: Finnhub data is static — need weekly refresh cron
  - Add scheduled re-fetch (float changes slowly but matters for small caps)

---

## Phase 3: Performance Tracking

### Goal: Measure if the scanner's picks actually work
- [ ] Record all scanner results to a `scan_history` DB table
- [ ] For each passed stock, record: symbol, time, price, all criteria values
- [ ] Next day: look up what happened (close price, max gain/loss during day)
- [ ] Calculate win rate, average gain on winners, average loss on losers
- [ ] Compare to baseline (e.g., buy any stock with 10%+ gap up regardless of filters)

---

## Phase 4: Alerts & Automation

- [ ] **Real-time alerts** when scanner finds a stock at market open
  - Email / Slack / SMS notification
  - Include: symbol, price, % change, relative volume, float, news headline
- [ ] **Scheduled scanning**: Auto-run at 9:00, 9:15, 9:30 AM ET
  - Use Windows Task Scheduler or cron
  - Write results to DB and send alert if new stocks appear
- [ ] **Auto-refresh UI**: Already has 60s auto-refresh toggle, ensure it works live

---

## Phase 5: UI Enhancements (future)

- [ ] **Intraday chart** per stock (click row → show 1m candle chart for today)
- [ ] **Historical performance overlay** (show what happened after scanner found it)
- [ ] **Watchlist**: Pin specific stocks across sessions
- [ ] **Multi-date comparison**: Show Feb 13, Feb 17, today side-by-side
- [ ] **Mobile-friendly layout**

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `database/collect_data.py` | Live data collector (run 24/7) |
| `database/backfill_optimized.py` | One-time historical backfill |
| `database/backtest_scanner.py` | Core filtering engine |
| `database/query_helpers.py` | All DB query methods |
| `database/fetch_fundamentals.py` | Finnhub float/market cap fetcher |
| `database/sanity_check.py` | Validate scanner vs ground truth |
| `backend/app.py` | Flask API server |
| `frontend/app.js` | AG Grid UI + API calls |
| `config.py` | All settings + SCANNER_CRITERIA |

## Running the System

```bash
# 1. Start data collector (keep running in background)
python database/collect_data.py

# 2. Start Flask API
python backend/app.py

# 3. Open browser to http://localhost:5000

# 4. Run sanity check for a specific date
python database/sanity_check.py 2026-02-13

# 5. Refresh fundamentals (run weekly)
python database/fetch_fundamentals.py
```
