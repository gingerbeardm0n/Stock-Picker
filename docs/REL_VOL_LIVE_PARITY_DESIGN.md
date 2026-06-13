# Rel-Vol Live Parity Design (Gap #1)

**Problem** (found 2026-06-12 parity audit): the simulators compute relative
volume from `rel_vol_cum_cache` (today's cumulative volume at 9:25 ÷ 30-day
average at the same minute) and enforce `min_relative_volume` (trial 173:
2.79x). The live runners hardcode `rel_vol = 10.0` because they run on Render
with **no database access**. Two consequences:

1. The `min_relative_volume` filter never fires live — live trades candidates
   the sim (and the optimizer that produced the config) would reject.
2. `rel_vol` is 30% of the ranker score — live watchlist ordering diverges
   from sim ordering whenever real rel-vol would not be ~uniform.

## Constraint map

| Piece | Where it lives | Available on Render? |
|---|---|---|
| Today's cumulative volume (numerator) | Tradier production quote `volume` field | YES — real-time |
| 30-day avg cumulative volume at 9:25 (denominator) | `rel_vol_cum_cache` in local TimescaleDB | NO |

So only the **denominator baseline** needs to be shipped to Render.

## Chosen approach: data branch + raw fetch

Nightly local job exports the baseline → pushes to a dedicated `data` branch
(never `main`, so no Render deploy is triggered) → live runner fetches the
raw file at session start with graceful fallback.

### 1. Export script (local, nightly)
`production/data/live_capture/export_rel_vol_baseline.py`
- Query: `SELECT symbol, AVG(cum_total) FROM rel_vol_cum_cache WHERE
  trade_date >= now()-30d AND minute_of_day = 565 GROUP BY symbol`
  (565 = 9:25 ET, same minute the sims use)
- Output: `data/rel_vol_baseline.json` —
  `{"as_of": "YYYY-MM-DD", "minute_of_day": 565, "baselines": {"SYM": avg, ...}}`
  ~12k symbols ≈ 300 KB.
- Commit + push to `data` branch (force-push, single-file branch; history
  irrelevant).
- Schedule with the existing nightly routine (after collector close / rel-vol
  cache update).

### 2. Live runner fetch (Render, session start)
- At init: GET
  `https://raw.githubusercontent.com/gingerbeardm0n/Stock-Picker/data/data/rel_vol_baseline.json`
  (5s timeout).
- Staleness guard: if `as_of` older than 5 trading days → log warning, still
  use it (stale baseline beats none).
- **Fallback**: fetch fails → `rel_vol = 10.0` (current behavior), log
  loudly. Filter becomes a no-op rather than blocking the session.

### 3. Live rel-vol computation (both runners)
At the 9:25 refresh (scalp) / watchlist build (VWAP):
```
rel_vol = quote.volume / baseline[symbol]   # if baseline > 0
        = 10.0                              # symbol missing / no baseline (same as sim default)
```
Then apply the SAME filter the sims apply: `rel_vol >= config.min_relative_volume`.

Note: sims default to 10.0 when a symbol has no 30-day history (recent IPO,
ticker change) — the live fallback matches that semantics exactly.

### 4. Timing caveat (accepted imprecision)
Tradier quote `volume` at 9:25 = cumulative volume since 4:00 AM premarket.
`rel_vol_cum_cache.cum_total` at minute 565 = cumulative DB volume to 9:25.
These match by construction (cache builds from 4am hour bars + minute bars).
Residual mismatch: Tradier consolidated tape vs Alpaca IEX feed undercounts —
the daily validation pipeline (stock_news_live / stock_candles_live_1m
comparisons) will quantify this; revisit threshold if systematic.

## Out of scope (separate gaps)
- Gap #3 (gap% basis: official open vs premarket last quote)
- Gap #5 (float data source for live)

## Rollout
1. Build export script + run once manually → verify JSON.
2. Create `data` branch with first export.
3. Wire fetch + computation into both live runners behind the fallback.
4. Deploy; next session logs show real rel-vol values.
5. Daily validation compares sim rel_vol vs live-logged rel_vol per symbol.
