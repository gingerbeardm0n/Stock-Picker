# Comprehensive Backfill Strategy

## Problem Statement

Current database state (as of Feb 22, 2026):
- **Minute data (8am-12pm)**: Good for Dec 2025 - Feb 2026 (3 months), missing Jan-Nov 2025
- **Hourly data (4am-8am)**: Essentially missing across all dates (max 1350 symbols vs 3500 needed)
- **Stock list used**: Single static snapshot from last week (4000 symbols at that time)

**Why this matters**: Stock prices change daily. Using a static list across 12 months is inaccurate.
- Stock at $8 on Jan 1 might be $25 on Jan 20 (outside $1-$20 range)
- Simulation should only include stocks that were actually in-range on each day

## Solution: Two-Phase Backfill

### Phase 1: Historical Tradable Stocks Snapshot (Jan 2025 - Feb 2026)

**Script**: `database/historical_tradable_stocks.py`

**What it does**:
1. For each trading day from Jan 1, 2025 - Feb 28, 2026
2. Fetches all tradable stocks from Alpaca (4000-5000 symbols)
3. Filters by current price ($1-$20 range)
4. Stores per-day stock lists in database table `tradable_stocks_by_date`

**Why this order**:
- Alpaca snapshot API gives current prices, not historical prices at specific times
- For production accuracy, we'd use minute bars (find first trade of each day)
- For initial backfill, snapshots are 80% accurate and much faster

**Database table created**:
```sql
CREATE TABLE tradable_stocks_by_date (
    date DATE NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    price DECIMAL(8, 2) NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, symbol)
);
```

**Run time**: ~5-10 hours (one snapshot API call per day, ~300 trading days)

**Cost**: ~300 API calls @ 200 req/min limit (well under 1 minute of quota)

---

### Phase 2: Backfill Candle Data Using Daily Stock Lists

**Script**: `database/backfill_with_daily_stocks.py`

**What it does**:
1. For each trading day
2. Loads the stock list from Phase 1 (for that day)
3. Backfills minute bars (8am-12pm ET) OR hourly bars (4am-8am ET)
4. Inserts into `stock_candles_1m` or `stock_candles_1h`

**Uses daily-accurate stock lists**: Only fetches data for stocks that were actually tradable on each day

**Run time**:
- Minute data (Jan-Nov 2025, ~220 trading days): ~2-4 hours
- Hourly data (Jan 2025-Feb 2026, ~300 trading days): ~1.5-2 hours

**Total time**: Phase 1 + Phase 2 = ~9-16 hours total (most of it is Phase 1 snapshots)

---

## Execution Plan

### Step 1: Phase 1 - Snapshot Tradable Stocks

**Terminal 1** (start and leave running):
```bash
cd /c/Repositories/Stock-Picker

# Initial run (full date range)
python database/historical_tradable_stocks.py \
  --start 2025-01-01 \
  --end 2026-02-28

# Or run for last N trading days as test
python database/historical_tradable_stocks.py --days 30
```

**Progress**:
- Logs progress every day
- Stores ~3500-4000 stocks per day
- Total: ~200K-220K records in `tradable_stocks_by_date` table

**Check completion**:
```python
from utils.query_helpers import StockDataDB

with StockDataDB() as db:
    cursor = db.conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT date) FROM tradable_stocks_by_date")
    print(f"Days with stock lists: {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM tradable_stocks_by_date")
    print(f"Total stock-date records: {cursor.fetchone()[0]:,}")
```

---

### Step 2: Phase 2a - Backfill Minute Data (Jan-Nov 2025)

Wait until Phase 1 completes, then:

**Terminal 2**:
```bash
cd /c/Repositories/Stock-Picker

# Backfill minute data for gap period
python database/backfill_with_daily_stocks.py \
  --type minute \
  --start 2025-01-01 \
  --end 2025-11-30
```

**Progress**:
- Logs each day's progress
- Expected: ~250-300 stocks per day × 240 minutes = ~60-72K candles per day
- Total for Jan-Nov: ~3.3-4M minute candles

**Check completion**:
```python
with StockDataDB() as db:
    cursor = db.conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM stock_candles_1m
        WHERE time AT TIME ZONE 'America/New_York' >= '2025-01-01'
          AND time AT TIME ZONE 'America/New_York' < '2025-12-01'
    """)
    print(f"Minute candles (Jan-Nov 2025): {cursor.fetchone()[0]:,}")
```

---

### Step 3: Phase 2b - Backfill Hourly Data (Jan 2025 - Feb 2026)

Can run in parallel with Step 2, or after:

**Terminal 3** (or after Step 2):
```bash
cd /c/Repositories/Stock-Picker

# Backfill hourly data for full range
python database/backfill_with_daily_stocks.py \
  --type hourly \
  --start 2025-01-01 \
  --end 2026-02-28
```

**Progress**:
- Expected: ~250-300 stocks per day × 4 hours = ~1K-1.2K candles per day
- Total for 13 months: ~13K-15.6K hourly candles

**Check completion**:
```python
with StockDataDB() as db:
    cursor = db.conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stock_candles_1h WHERE symbol IN (SELECT DISTINCT symbol FROM stock_candles_1m)")
    print(f"Hourly candles: {cursor.fetchone()[0]:,}")
```

---

## Rate Limiting & Timing

**Alpaca API limit**: 200 requests per minute (default for Premium)

**Phase 1 rate**: ~1 req/day (snapshot API) = no issues

**Phase 2 rate**: Chunked at 50 symbols per request
- Minute backfill: ~5-7 chunks/day × 55 days = ~280-385 chunks = ~2-3 days CPU time
- Hourly backfill: ~5-7 chunks/day × 55 days = ~280-385 chunks = ~2-3 days CPU time

**With 0.3s throttle per chunk**: Stays well under 200 req/min

---

## Verification After Backfill

Run the diagnostic script again to confirm:

```bash
python database/diagnose_data_coverage.py
```

**Expected results**:
```
Minute Data (8am-12pm):
  Jan 2026:    20/20 days, 3600+ avg symbols ✅
  Dec 2025:    22/22 days, 3500+ avg symbols ✅
  Nov 2025:    20/20 days, 3200+ avg symbols ✅
  Oct 2025:    20/20 days, 3200+ avg symbols ✅
  ... (Jan-Oct 2025) ...
  Jan 2025:    20/20 days, 2800+ avg symbols ✅

Hourly Data (4am-8am):
  Jan-Feb 2026: 20/20 days, 3000+ avg symbols ✅ (NEW)
  Dec 2025:     22/22 days, 3000+ avg symbols ✅ (NEW)
  ... (Jan-Dec 2025) ...
  Jan 2025:     20/20 days, 2800+ avg symbols ✅ (NEW)

Exhaustive Periods:
  [SUCCESS] FOUND 1+ COMPLETE DATA BLOCK(S)
  Block 1: 2025-01-02 to 2026-02-21 (13+ months)
  Duration: 200+ trading days
  Avg 4am-8am hourly: 3000+ symbols ✅
  Avg 8am-12pm minute: 3500+ symbols ✅
```

---

## Estimated Timeline

| Phase | Task | Duration | Start |
|-------|------|----------|-------|
| 1 | Historical stock snapshots (300 trading days) | 5-10 hours | Day 1 |
| 2a | Minute backfill (Jan-Nov 2025) | 2-4 hours | Day 1 (after Phase 1) |
| 2b | Hourly backfill (Jan-Feb 2026) | 1.5-2 hours | Day 1 (parallel with 2a) |
| 3 | Verification | 1 hour | Day 2 |
| **Total** | | **~9-16 hours** | |

**Note**: Phases 2a and 2b can run in parallel (different terminals/machines). Total is mostly waiting on Phase 1 snapshots.

---

## Next Steps After Backfill

Once you have exhaustive data (Jan 2025 - Feb 2026, 3500+ stocks daily):

1. **Run Jan 6 simulation**: `python simulator/simulate_date.py --date 2025-01-06`
   - Should show real trades (currently shows 0)

2. **Validate patterns**: Compare Jan 2025 results vs current (Dec 2025-Feb 2026)
   - Check if pattern detection is consistent across date range
   - Identify if thresholds need seasonal adjustment

3. **Run optimization plan**: Execute `strategy/SIMULATION_OPTIMIZATION_PLAN.md`
   - Sensitivity analysis on entry/exit parameters
   - Walk-forward validation (train Jan-Sep 2025, test Oct-Dec 2025)
   - Optuna optimization for 27 key parameters

---

## Troubleshooting

### "tradable_stocks_by_date table not found"
- Run Phase 1 first: `python historical_tradable_stocks.py --start 2025-01-01 --end 2026-02-28`

### "No stocks found for date"
- Check if Phase 1 ran for that date: `SELECT * FROM tradable_stocks_by_date WHERE date = '2025-01-06'`
- If empty, Phase 1 didn't run for that date

### Slow performance / Rate limiting
- Increase throttle sleep (currently 0.3s per chunk): edit scripts to `time.sleep(0.5)`
- Process fewer symbols per chunk: change `chunk_size=50` to `chunk_size=25`

### Duplicate key errors on insert
- Scripts use `ON CONFLICT ... DO UPDATE` (PostgreSQL upsert)
- Safe to restart from same date; will replace old data

---

## Database Cleanup (Optional)

To clear and restart backfill for specific date range:

```sql
-- Clear tradable stocks for a date range
DELETE FROM tradable_stocks_by_date
WHERE date BETWEEN '2025-01-01' AND '2025-01-31';

-- Clear minute candles for a date range
DELETE FROM stock_candles_1m
WHERE time AT TIME ZONE 'America/New_York' >= '2025-01-01'
  AND time AT TIME ZONE 'America/New_York' < '2025-02-01';

-- Clear hourly candles for a date range
DELETE FROM stock_candles_1h
WHERE time AT TIME ZONE 'America/New_York' >= '2025-01-01'
  AND time AT TIME ZONE 'America/New_York' < '2025-02-01';
```
