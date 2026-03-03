# TimescaleDB Storage Analysis

## Your Setup: Self-Hosted TimescaleDB

You're running a self-hosted TimescaleDB instance in Docker (container: `stockdata-timescale`), which means:

✅ **NO storage limits from Timescale** — Limited only by your disk space
✅ **You control the infrastructure** — No licensing restrictions
✅ **Cost**: Free forever (open-source PostgreSQL + Timescale extension)

---

## Storage Requirements for 12-Month Backfill

### Data Collection Plan: Hybrid Timeframes
- **5-minute bars** (4am-8am): Premarket session, lower noise
- **1-minute bars** (8am-12pm): Trading morning, precise signals
- **Hour bars** (4am-8pm): Full day data (seeding, diagnostics)
- **Daily bars** (all year): Volume reference

### Calculation for 4,000 Symbols × 252 Trading Days

**5-minute bars (4am-8am)**
- Bars per day: 48 (4 hours × 12 bars/hour)
- Bars per symbol per year: 48 × 252 = 12,096
- Total bars: 4,000 × 12,096 = **48.4 million**
- Storage: ~4.8 GB (at ~100 bytes/bar)

**1-minute bars (8am-12pm)**
- Bars per day: 240 (4 hours × 60 bars/hour)
- Bars per symbol per year: 240 × 252 = 60,480
- Total bars: 4,000 × 60,480 = **241.9 million**
- Storage: ~24.2 GB

**Hour bars (4am-8pm, all day)**
- Bars per day: 16 hours/day
- Bars per symbol per year: 16 × 252 = 4,032
- Total bars: 4,000 × 4,032 = **16.1 million**
- Storage: ~1.6 GB

**Daily bars (252 trading days)**
- Total bars: 4,000 × 252 = **1 million**
- Storage: ~0.1 GB

### **TOTAL STORAGE: ~30 GB** (4am-12pm data only)

This fits comfortably on any modern system. For context:
- Average laptop: 256-512 GB available
- Docker images can use allocated space dynamically
- TimescaleDB hypertable chunking is storage-efficient

---

## Comparison: TimescaleDB Cloud vs Self-Hosted

| Feature | Self-Hosted (Your Setup) | Timescale Cloud Free | Timescale Cloud Paid |
|---------|--------------------------|----------------------|---------------------|
| Storage Limit | Unlimited (disk-bound) | **30-day trial only** | 32GB - 2TB (tiers) |
| Cost | Free | Free (trial only) | $50-$2,000/month |
| Data Retention | Permanent | Trial only | Permanent |
| API Calls | Unlimited | Limited | Unlimited |
| Best For | Backesting, research | Testing | Production |

---

## Recommendation: Stay Self-Hosted

Your current setup is **ideal for this project**:

1. ✅ Unlimited storage for 12-month backfill
2. ✅ Full control over data
3. ✅ Zero cost
4. ✅ Fast local access (no network latency)
5. ✅ Easy snapshot/backup to external drive

**No changes needed** — Your Docker container can handle 30 GB without issues.

---

## Updated Backfill Script Changes

The revised `backfill_optimized.py` now:

### New Functions
1. **`backfill_5min_bars_premarket()`** — Fetches 5-minute bars for 4am-8am
2. **`backfill_1min_bars_trading()`** — Fetches 1-minute bars for 8am-12pm

### Storage Optimization
- **Before**: 480 bars/day × 4000 × 252 = 482.8 million bars = **48 GB**
- **After**: 48 + 240 bars/day × 4000 × 252 = 288.4 million bars = **~29 GB** (40% reduction)

### Progress Tracking
- Separate progress keys for each window: `5min_4to8_batch_N`, `1min_8to12_batch_N`
- Safe to re-run (ON CONFLICT DO NOTHING on all inserts)
- Resumable after interruption

### API Efficiency
- 5-minute premarket: Less noisy, sufficient for EMA-9 seeding (48 bars = >5 hours of history by 8am)
- 1-minute trading: Precise entry/exit signals needed during peak volatility (9:30-11am)
- Dual-timeframe approach leverages Ross Cameron's preference for 5-min/15-min charts

---

## Next Steps

1. **Start backfill**: `python data/backfill/backfill_optimized.py`
   - Choose 12 months of data
   - Select medium batch size (200 stocks/batch)
   - Estimated runtime: 5-10 days with parallel batching

2. **Monitor progress**: Check logs or review `backfill_optimized_progress.json`

3. **Verify data**: Run simulator on subset (e.g., Feb 3-18) before full backfill completes

4. **Scale up**: Once happy with results, extend to 24 months or full 2025 data

---

## Storage Beyond 12 Months (Future)

If you later want to backfill multiple years:
- 2 years: ~58 GB
- 3 years: ~87 GB
- 5 years: ~145 GB

All still manageable with a standard external SSD backup if needed.
