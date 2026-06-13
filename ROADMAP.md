# Stock Scanner — Master Roadmap

> **⚠️ SUPERSEDED (2026-06-13).** This describes the pre-pivot monolith (Flask + 5-pillar
> scanner + the "Phase 6" ML parameter-sweep vision). The project pivoted June 2026 to two
> standalone, individually-optimized strategies (Opening Bell Scalp + VWAP Reclaim). For the
> current plan + ranked backlog see **`docs/STRATEGY_ROADMAP.md`**. Kept for history.

## Architecture Overview

```
Alpaca API (data feed)
    |
    v
collect_data.py  ──────►  TimescaleDB (PostgreSQL)
                           ├── stock_candles_1m  (hybrid: 5-min 4am-8am + 1-min 8am-12pm)
                           ├── stock_candles_1h  (hour bars, 4am-8pm)
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

## Phase 6: Large-Scale Simulation & ML Analysis (IN PROGRESS)

### Goal: Data-Driven Strategy Optimization via Massive Simulation Sweeps

Transform trading logic from hand-tuned rules → statistically validated, ML-scored filters.

### Part A: Historical Data Expansion (CURRENT PRIORITY)

**Current state**: Feb 3-18, 2026 (~11 trading days, 44 trades = too small for confidence)

**Target**: 12 months of historical data (all of 2025 + current) = 252 trading days, ~750 trades

**Data structure** (optimize storage + query speed):
- **4am-8am (premarket)**: 1-hour bars only (5 bars/day, ~10M rows for 4000 symbols)
  - Used to seed EMA-9, MACD, and build relative volume baseline
  - 50% storage reduction vs minute data
- **8am-12pm (trading window)**: 1-minute bars (240 bars/day, ~300M rows for 4000 symbols)
  - Critical for entry/exit pattern detection at 9:30-11am
  - Full precision needed
- **12pm-8pm**: Skip entirely (our strategy doesn't trade after 11am)

**Backfill plan**:
1. Run `backfill_optimized.py` for all of 2025 (Jan 1 - Dec 31)
   - Start with most recent dates (current risk of corrupted data lower)
   - Work backward to Jan 2025
   - Estimated time: 2-4 days (depending on parallel jobs)
2. Verify data with `sanity_check.py` on random sample dates
3. Expected final DB size: ~200GB (manageable for TimescaleDB)

**Why 12 months?**
- 252 trading days × 2-3 trades/day = 500-750 trades (statistical significance ✅)
- Captures bull markets, crashes, volatility regimes, seasonal effects
- Enough to validate filter interactions without diminishing returns

### Part B: Simulation Parameter Sweep Engine (DESIGN PHASE)

**Goal**: Run 1000s of simulations with varied thresholds, track which produce best results

**Parameters to sweep**:
1. **Entry gates**:
   - Relative volume threshold: 3x, 4x, 5x, 6x, 7x
   - Price range: $1-$20, $2-$20, $5-$20, $2-$15
   - Float threshold: 10M, 15M, 20M, 30M
   - Gain threshold: 8%, 10%, 12%, 15%
   - Min buying volume: 30K, 50K, 75K

2. **Position sizing**:
   - max_position_pct: 10%, 15%, 20%, 25%, 30%
   - risk_pct: 1%, 1.5%, 2%, 2.5%, 3%

3. **Exit rules**:
   - SELLING_PRESSURE threshold: 1.5x, 2.0x, 2.5x, 3.0x
   - TIME_DECAY hour: 10am, 11am, 12pm
   - EMA period: 7, 9, 11, 13

4. **Trading window**:
   - Entry start: 9:30am, 10:00am
   - Entry end: 10:30am, 11:00am, 11:30am
   - Exit deadline: 11:00am, 11:30am, 12:00pm

**Expected combinations**: 5 × 4 × 3 × 3 × 3 × 5 × 2 × 4 × 2 × 3 = millions of variations
- Run with representative subsets: 10% sampling = 100K+ simulations

**Simulation outputs per run**:
```json
{
  "parameters": {
    "rel_vol_min": 5.0,
    "max_position_pct": 20,
    "selling_pressure_threshold": 2.0,
    ...
  },
  "results": {
    "date_range": "2025-01-01 to 2025-12-31",
    "total_trades": 742,
    "total_pnl": 3847,
    "win_rate": 0.483,
    "sharpe_ratio": 1.23,
    "max_drawdown": -247,
    "best_day": 238,
    "worst_day": -105,
    "pattern_breakdown": {
      "FLAT_TOP": {"count": 183, "win_rate": 0.58, "pnl": 2104},
      "ABCD": {"count": 74, "win_rate": 0.38, "pnl": -156},
      ...
    }
  }
}
```

### Part C: Feature Importance Analysis (ML PHASE)

**Input**: 100K+ simulation results (each with different parameter combos)

**Analysis goals**:
1. **Correlation matrix**: Which parameters interact? (e.g., high position size + tight exits = risky)
2. **Feature importance**: Rank by impact
   - Position sizing: 80% of P&L variance
   - Rel vol threshold: 60% of variance
   - Exit threshold: 40% of variance
   - Pattern selection: 35% of variance
3. **Non-linear patterns**: Random Forest / Gradient Boosting to find sweet spots
   - "High position size works ONLY with tight SELLING_PRESSURE threshold"
   - "ABCD pattern needs higher rel vol than FLAT_TOP"
   - "Win rate peaks 9:30-10:30, drops after 11:00"
4. **Scoring system**: Assign weights
   - "If score = rel_vol + 2×position_sizing + 0.5×exit_threshold, we maximize returns"

**Output**: Adaptive thresholds
- Instead of fixed `rel_vol_min=5.0` for all stocks, generate: `rel_vol_min = 5.0 - 0.1×float_score + 0.2×vol_score`
- Different rules for different market conditions (bull vs volatility)

### Part D: LLM Integration (EXPLORATORY)

Feed results to a language model:
```
Here are 1000 simulation runs with different parameters and their P&L results.
What patterns do you see? Which factors matter most?
What would you recommend we change about the trading strategy?
```

Goal: Discover non-obvious insights (e.g., "You're exiting too early; combine EMA with volume")

### Timeline
- **Week 1-2**: Backfill all 2025 data (parallel backfill, ~5-10 days runtime)
- **Week 3**: Build parameter sweep engine + run initial 10K simulations
- **Week 4**: Analyze correlations, identify top 100 parameter combinations
- **Week 5**: ML feature importance analysis
- **Week 6**: LLM pattern discovery + recommendations
- **Week 7+**: Refine strategy based on findings, repeat with tighter parameter ranges

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `data/collector/collect_data.py` | Live data collector (run 24/7) |
| `data/backfill/backfill_optimized.py` | One-time historical backfill |
| `data/backfill/fill_gaps.py` | Gap recovery (detects downtime) |
| `utils/backtest_scanner.py` | Core filtering engine |
| `utils/query_helpers.py` | All DB query methods |
| `utils/trading_calendar.py` | NYSE holiday calendar |
| `services/fetch_fundamentals.py` | Finnhub float/market cap fetcher |
| `maintenance/sanity_check.py` | Validate scanner vs ground truth |
| `maintenance/db_status.py` | Database coverage report |
| `simulator/simulation_engine.py` | Backtesting engine |
| `simulator/simulate_date.py` | Single-day simulation CLI |
| `simulator/simulate_date_range.py` | Multi-day simulation CLI |
| `backend/app.py` | Flask API server |
| `frontend/app.js` | AG Grid UI + API calls |
| `config.py` | All settings + SCANNER_CRITERIA |

## Running the System

```bash
# 1. Start data collector (keep running in background)
python data/collector/collect_data.py

# 2. Start Flask API
python backend/app.py

# 3. Open browser to http://localhost:5000

# 4. Run simulations
python simulator/simulate_date.py --date 2026-02-13
python simulator/simulate_date_range.py --start 2026-02-03 --end 2026-02-18

# 5. Run sanity check for a specific date
python maintenance/sanity_check.py 2026-02-13

# 6. Refresh fundamentals (run weekly)
python services/fetch_fundamentals.py

# 7. Fill data gaps (after outages)
python data/backfill/fill_gaps.py 2026-02-19
```
