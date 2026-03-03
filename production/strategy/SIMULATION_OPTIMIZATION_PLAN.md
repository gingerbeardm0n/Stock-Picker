# Simulation Optimization Plan

*Documented: Feb 21, 2026 | Updated: Feb 21, 2026 (Category C confirmed, execution plan finalized)*
*Framework: Profit Factor + Multi-Objective Testing | Data: 2025 Backfill (252 trading days, 4000 stocks)*

---

## Overview

This document outlines the framework for optimizing the trading strategy using large-scale historical simulation before deploying live. The goal is to validate that parameter choices are robust across market conditions, not just lucky on the training data.

**Key insight**: With ~44-48 meaningful parameters across 3 categories and 2025's year of data (252 trading days), we can run 1,500-2,000 Optuna trials efficiently to find parameter sets that maximize strategy quality metrics.

**Status**: All infrastructure is built. Ready to begin optimization runs.
- ✅ `trading/entry_engine.py` — 15-18 tunable parameters
- ✅ `trading/exit_engine.py` — 21 tunable parameters via `ExitConfig` (confirmed after Category C gap analysis)
- ✅ `trading/portfolio_manager.py` — observer for daily rule counterfactuals (no enforcement)
- ✅ `simulator/simulation_engine.py` — accepts `ExitConfig`, enriched indicators, portfolio tracking
- ⏳ `optimizer/` — BUILD NEXT (this plan describes what to build)

---

## Parameter Categories

### Category A: Stock Selection & Risk Management (8 parameters)

What stocks to consider trading at all. Primarily driven by Ross Cameron's 5 Pillars.

| Parameter | Current | Tunable Range | Impact |
|-----------|---------|---------------|--------|
| `min_premarket_gain` | 10% | 8-20% | Controls how strong the premarket move must be |
| `min_relative_volume` | 5.0x | 3-10x | 5 Pillars requirement; 10x+ is "hot" |
| `min_buying_volume` | 50,000 shares | 20K-150K | Ensures liquidity for entry/exit |
| `max_float` | 20M shares | 10M-30M | Lower float = higher volatility; Ross prefers <20M |
| `max_market_cap` | $500M | $300M-$1B | Filters out mega-cap moves |
| `max_position_pct` | 20% | 10-30% | % of account per trade |
| `risk_pct` | 2% | 1-4% | % account risked per trade (for stop calculation) |
| `daily_max_loss_pct` | 3% | 2-5% | Daily loss limit for portfolio rule tracking |

**Where**: `simulator/simulation_engine.py` → `SCANNER_CRITERIA` dict + `SimulationRunner.__init__()` params.

---

### Category B: Entry Logic — Pattern Detection & Technicals (15-18 parameters)

When to enter during the trading window (9:30 AM - 12:00 PM ET).

**Technical Filters** (must-pass gates):
- EMA-9: price must be above the 9-period EMA
- MACD: histogram must be positive (bullish momentum)
- Trending up: majority of recent bars green with higher closes
- Volume on green bars > volume on red bars

**Pattern-Specific Thresholds**:

| Pattern | Confidence | Key Parameters |
|---------|-----------|----------------|
| Bull Flag | 5 stars | Pole volume threshold (0.8), flag light vol (0.7), breakout vol (0.8) |
| Micro Pullback | 4 stars | Green bar threshold (0.6), pullback depth safety (0.98) |
| ABCD | 4 stars | B pullback minimum (0.15), D volume threshold (0.8) |
| Dip Buy | 3 stars | Light vol threshold (0.65) |
| Flat Top | 3 stars | Resistance tolerance ($0.03), min touches (2) |

**Where**: `trading/entry_engine.py` + `trading/patterns.py` + `config.py`

---

### Category C: Exit Logic (21 parameters via `ExitConfig`) ← **CONFIRMED after gap analysis**

*Confirmed Feb 21 after comparing exit_engine.py vs UTS_EXIT_RULES.md + UTS_RISK_MANAGEMENT.md.*
*See `strategy/CATEGORY_C_GAP_ANALYSIS.md` for full details.*

All parameters live in `trading/models.py` → `ExitConfig` dataclass.

#### Scaling Targets (4 params)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `target1_ratio` | 2.0 | 1.5–3.0 | R/R for first profit target |
| `target2_ratio` | 3.0 | 2.0–4.0 | R/R for second profit target |
| `target1_qty_pct` | 0.50 | 0.25–0.75 | Fraction to sell at T1 |
| `target2_qty_pct` | 0.25 | 0.10–0.50 | Fraction to sell at T2 |

#### Trailing Stop (1 param)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `trailing_stop_distance` | 0.0 | 0.0–0.15 | 0 = disabled; 0.05 = 5-cent trail |

#### Time Decay (4 params)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `time_decay_hour` | 11 | 10–12 | Primary exit hour |
| `early_time_decay_hour` | 0 | 0,10 | 0 = disabled |
| `early_time_decay_minute` | 45 | 15–45 | Minutes past early hour |
| `early_time_decay_min_gain_pct` | 5.0 | 2.0–10.0 | "Major gains" threshold to skip early exit |

#### Selling Pressure (2 params)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `selling_pressure_ratio` | 2.0 | 1.5–3.0 | selling_vol / buying_vol threshold |
| `selling_pressure_qty_pct` | 0.50 | 0.25–1.0 | Fraction to sell on pressure |

#### MACD Flip (2 params, Phase 3)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `enable_macd_flip_exit` | False | True/False | Enable MACD histogram flip detection |
| `macd_flip_qty_pct` | 0.50 | 0.25–1.0 | Fraction to sell on flip |

#### Resistance Level (4 params, Phase 3)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `enable_resistance_exit` | False | True/False | Enable prior-day high exits |
| `resistance_touch_threshold` | 2 | 1–3 | Exit on Nth touch |
| `resistance_exit_qty_pct` | 0.50 | 0.25–1.0 | Fraction to sell |
| `resistance_tolerance` | 0.03 | 0.01–0.05 | $ within prior-high = "touched" |

#### Volume Dry-Up (3 params, Phase 4)
| Parameter | Default | Range | Notes |
|-----------|---------|-------|-------|
| `enable_volume_dry_up_exit` | False | True/False | Enable volume collapse exits |
| `volume_dry_up_threshold` | 0.60 | 0.40–0.80 | < N% of avg vol = dry |
| `volume_dry_up_qty_pct` | 0.50 | 0.25–1.0 | Fraction to sell |

**Total Category C: 20 tunable parameters** (Phase 3/4 features are optional booleans that Optuna can toggle)

---

## Total Parameter Count

| Category | Parameters | Status |
|----------|------------|--------|
| A (Stock Selection) | 8 | ✅ Ready |
| B (Entry Logic) | 15-18 | ✅ Ready |
| C (Exit Logic) | 20 | ✅ Ready (ExitConfig) |
| **TOTAL** | **43-46** | **✅ Ready for optimization** |

---

## Results Storage: SQLite

**Decision**: SQLite as primary storage for all optimization runs. Text logs for real-time monitoring.

**Why SQLite over alternatives:**
- Zero dependencies (Python stdlib)
- Single `.db` file — copyable, backupable, shareable
- Queryable with SQL or pandas (any question answerable without re-running)
- Optuna natively supports SQLite storage → free `optuna-dashboard` UI
- Handles 280,000+ trade rows without issue
- No server setup, no cloud, no cost

**Schema (two tables):**

```sql
-- One row per simulation run
CREATE TABLE runs (
    run_id      INTEGER PRIMARY KEY,
    created_at  TEXT,
    phase       TEXT,        -- 'sweep', 'optuna'
    trial_id    INTEGER,     -- Optuna trial number (if applicable)
    sim_date    TEXT,        -- Trading date simulated (YYYY-MM-DD)
    -- Category A params (JSON blob for flexibility)
    params_a    TEXT,
    -- Category B params (JSON blob)
    params_b    TEXT,
    -- Category C params (JSON blob from ExitConfig)
    params_c    TEXT,
    -- Aggregate metrics
    total_pnl   REAL,
    win_rate    REAL,
    trade_count INTEGER,
    profit_factor REAL,
    max_drawdown REAL,
    -- Portfolio rule counterfactuals
    green_to_red_fired    INTEGER,
    daily_max_loss_fired  INTEGER,
    give_back_half_fired  INTEGER
);

-- One row per trade (linked to run)
CREATE TABLE trades (
    trade_id    INTEGER PRIMARY KEY,
    run_id      INTEGER,
    sim_date    TEXT,
    symbol      TEXT,
    entry_time  TEXT,
    entry_price REAL,
    exit_time   TEXT,
    exit_price  REAL,
    exit_reason TEXT,
    pattern     TEXT,
    shares      INTEGER,
    pnl         REAL,
    rel_vol     REAL,
    float_shares REAL
);
```

**With this schema, example queries after optimization:**
```sql
-- Top 10 parameter sets by profit factor
SELECT trial_id, profit_factor, win_rate, trade_count
FROM runs WHERE phase = 'optuna'
ORDER BY profit_factor DESC LIMIT 10;

-- Does trailing stop help or hurt?
SELECT json_extract(params_c, '$.trailing_stop_distance') as trail,
       AVG(profit_factor), COUNT(*)
FROM runs WHERE phase = 'optuna'
GROUP BY trail ORDER BY AVG(profit_factor) DESC;

-- Per-pattern win rate in top configs
SELECT pattern, COUNT(*), AVG(pnl), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as wr
FROM trades WHERE run_id IN (SELECT run_id FROM runs ORDER BY profit_factor DESC LIMIT 50)
GROUP BY pattern;
```

---

## Execution Plan

### Files to Build (optimizer/)

```
optimizer/
├── run_config.py       # RunConfig dataclass: all A+B+C params in one object
├── results_db.py       # SQLite schema + write_run() / write_trades() / query helpers
├── simulate_one.py     # Wraps SimulationRunner for one date → returns metrics dict
├── sweep.py            # Sensitivity sweep: one-at-a-time over each A+C param
├── optuna_run.py       # Bayesian optimization: 1,500+ trials across A+B+C
└── analyze.py          # CLI: top configs, parameter importance, export to CSV
```

### Commands You'll Run

```bash
# Step 1: Sensitivity sweep (~10-30 min, validates harness works)
python optimizer/sweep.py --start 2025-01-01 --end 2025-09-30 --db results/sweep.db

# Step 2: Optuna optimization (~3-4 hours, resumable with Ctrl+C)
python optimizer/optuna_run.py --trials 1500 --start 2025-01-01 --end 2025-09-30 --db results/optuna.db

# Step 3: Walk-forward validation (~1 hour)
python optimizer/optuna_run.py --validate --best-n 5 --start 2025-10-01 --end 2025-12-31 --db results/optuna.db

# Analysis (any time)
python optimizer/analyze.py --db results/optuna.db --top 10
```

**Note on resumability**: Optuna stores trial state in SQLite. If you Ctrl+C during a run, restart with the same `--db` path and it continues from where it stopped.

---

## Objective Function: What We're Maximizing

Run three objectives and compare results. Each is computed per trial (one complete year of trading days).

### Primary: Profit Factor
```
Profit Factor = Gross Wins / Gross Losses
```
- > 1.5 = profitable strategy
- > 2.0 = high-quality (Ross Cameron standard)
- Resistant to outliers (one big lucky win doesn't skew it)

### Secondary: Total Return %
```
Return% = (Final Balance - Starting Balance) / Starting Balance × 100
```

### Tertiary: Risk-Adjusted Return
```
Score = Return% - 0.25 × Max_Drawdown%
```
- 75% weight on return, 25% weight on consistency
- Reflects stated preference: care about profits, but not indifferent to risk

**Optuna approach**: Run three separate optimization studies (one per objective), then compare the top parameter sets from each. If they converge on similar params, the strategy has a real edge. If they diverge, you'll understand the profit-vs-risk tradeoff.

---

## Sensitivity Analysis: Understanding Which Parameters Matter

**One-at-a-time (OAT) approach:**
1. Set all parameters to current defaults
2. For param #1 (`min_premarket_gain`): run simulations at 8%, 10%, 12%, 15%, 20% — record Profit Factor
3. Reset to default, move to param #2
4. Repeat for all Category A + C parameters (B is better handled by Optuna directly)

**What you learn:**
- Steep slope = parameter matters a lot → include in Optuna with wide range
- Flat slope = barely affects results → fix at default, exclude from Optuna

**Expected outcome**: ~15-20 of the 43-46 parameters show meaningful sensitivity. These drive Optuna's search; the rest are held at defaults.

**Important**: Run the sweep BEFORE the main Optuna run. If sweep shows a parameter has no effect, you can remove it from the Optuna search space entirely — reduces trial overhead.

---

## Walk-Forward Validation

**After optimization is complete**, validate the best parameter set on unseen data:

1. **Train period**: Jan 1 – Sep 30, 2025 (9 months, ~190 trading days)
2. **Test period**: Oct 1 – Dec 31, 2025 (3 months, ~63 trading days)

**Pass criteria**: Test Profit Factor must be ≥ 80% of training Profit Factor.
- Train PF = 2.0 → Test PF ≥ 1.6 ✅
- Train PF = 2.0 → Test PF = 0.9 ❌ (overfit to 2025 market conditions)

If validation fails, it means the optimized parameters found a quirk in Jan-Sep market conditions rather than a genuine edge. Don't trade live with those parameters.

---

## Portfolio Rule Analysis (Bonus, Free Data)

Every simulation run — including ALL optimization trials — will automatically capture whether the three portfolio rules would have fired:
- **Daily Max Loss**: Would stop-trading have applied?
- **Green-to-Red**: Did the account go green then red?
- **Give-Back-Half**: Did we hit a profit peak and give back >50%?

Since `portfolio_manager.py` is an observer with no enforcement cost, this data comes for free on every trial. After 1,500 Optuna trials across 190 trading days (285,000 simulation-days), we'll have statistically solid answers to: **does an automated algorithm need these emotional guardrails at all?**

The `portfolio_events` table will capture this aggregated. Analysis:
```sql
-- How often does green-to-red fire across all trials?
SELECT AVG(green_to_red_fired) as fire_rate FROM runs WHERE phase = 'optuna';

-- Do rules fire more on losing parameter sets?
SELECT green_to_red_fired, AVG(profit_factor) FROM runs GROUP BY green_to_red_fired;
```

---

## Two-Track Testing (Original Plan — Now Modified)

The original plan described TEST 1 (staged) and TEST 2 (all-at-once Optuna). **Updated recommendation:**

**Run TEST 2 (Optuna A+B+C) first** — faster (3-4 hrs vs 15 hrs) and Optuna's parameter importance scores give you the same insight as the staged sensitivity sweep.

**Run sensitivity sweep separately** (before Optuna) to:
1. Validate the harness is working on a small number of runs
2. Identify parameters with flat sensitivity to remove from Optuna search space
3. Gain intuition before committing to a multi-hour run

**Skip grid search entirely** — Optuna is strictly better for any search space with more than 4-5 parameters.

---

## Timeline & Execution Path

### Immediate (Build Optimizer)
1. Build `optimizer/` directory and all 5 files
2. Key dependency: `pip install optuna tqdm`
3. Test with 10-trial Optuna run on 5 dates before running full year

### Run 1: Sensitivity Sweep (~30 min wall time)
- Sweep Category A + C params (one at a time)
- Data: 2025 Jan–Sep
- Output: `results/sweep_2025.db`
- Purpose: Validate harness + identify flat params to exclude

### Run 2: Optuna Full Optimization (~3-4 hours, can run overnight)
- A+B+C simultaneously, 1,500 trials
- Data: 2025 Jan–Sep
- Output: `results/optuna_2025.db`
- Real-time monitoring: `optuna-dashboard results/optuna_2025.db`

### Run 3: Walk-Forward Validation (~1 hour)
- Take top 5 parameter sets from Run 2
- Simulate Oct–Dec 2025
- Output: Added to `results/optuna_2025.db` with phase='validation'

### Run 4+: Live Micro-Position Testing
- Best validated parameter set
- Real money, 0.5-1% risk
- Separate from simulation infrastructure

---

## Success Criteria

An optimization run is successful if:
1. ✅ Found parameter sets with Profit Factor > 2.0 on training data (Jan-Sep 2025)
2. ✅ Profit Factor ≥ 1.6 on walk-forward test (Oct-Dec 2025)
3. ✅ Win rate > 40%
4. ✅ Consistent across days (not dependent on one lucky outlier)
5. ✅ Per-trade analysis confirms pattern reliability (Bull Flag > 50% win rate expected)
6. ✅ Portfolio rule analysis shows rules help/hurt < $X over full year (empirically answered)

---

## Resources & Reference

- **Strategy documentation**: `strategy/UTS_ENTRY_RULES.md`, `UTS_EXIT_RULES.md`, `UTS_RISK_MANAGEMENT.md`
- **Category C gap analysis**: `strategy/CATEGORY_C_GAP_ANALYSIS.md`
- **Exit config**: `trading/models.py` → `ExitConfig` (all C parameters)
- **Optimization code (to build)**: `optimizer/`
- **Simulation infrastructure**: `simulator/simulation_engine.py`, `trading/entry_engine.py`, `trading/exit_engine.py`
- **Historical data**: 2025 backfill in TimescaleDB (4000 symbols, 252 trading days)
- **Quick test**: `python simulator/simulate_date.py --date 2025-06-15`
- **Range test**: `python simulator/simulate_date_range.py --start 2025-01-01 --end 2025-01-31`

---

**Next action**: Build `optimizer/` directory — start with `run_config.py` + `results_db.py` (the foundation), then `simulate_one.py`, then `sweep.py` and `optuna_run.py`.
