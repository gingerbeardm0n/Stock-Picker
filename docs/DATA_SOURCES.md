# Data Sources & API Configuration

> Maintained by the historian skill. Records what APIs we use, what tier/plan, what they provide,
> and when they last worked. Prevents the "wait, how did we backfill that?" problem.

## Active Sources

### Alpaca (Primary — Historical Data + News)
- **Account**: Free tier (live account, no funding required)
- **Env vars**: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY` in `production/.env.paper`
- **Base URL**: `https://api.alpaca.markets`
- **Provides**:
  - Historical minute bars (all US equities, 7+ years back) — **FREE**
  - Historical daily bars — **FREE**
  - Historical hourly bars — **FREE**
  - News API (real-time + historical, 200 req/min) — **FREE**
  - Trading calendar (`/v2/calendar`) — **FREE**
- **Rate limit**: 200 calls/min (free plan)
- **Last verified working**: 2026-06-09 (minute bars for Jan 2025 - Jun 2026)
- **Key history**:
  - `AK42...` — original key, used for all 2021-2026 backfill. Died when new keys generated 2026-06-09.
  - `AKIJ...` — new live key, generated 2026-06-09. Works for data + news.
- **Scripts that use it**:
  - `production/data/backfill/backfill_optimized.py` — main historical backfill
  - `production/data/backfill/backfill_news.py` — news article backfill
  - `production/backend/news_fetcher.py` — live news fetch via `NewsFetcher`
  - `production/utils/trading_calendar.py` — trading day calendar
- **IMPORTANT**: Regenerating API keys in the Alpaca dashboard **invalidates all previous keys**.
  The old key immediately returns 401. This is why `AK42...` stopped working.
- **IMPORTANT**: Free tier DOES provide full historical minute bars. Earlier confusion (Jun 9 2026)
  was caused by testing on non-trading days (weekends). Minute bars work on all valid trading days.

### Alpaca Paper (Order Execution)
- **Account**: Paper trading — separate from live data account
- **Env vars**: `APCA_PAPER_KEY_ID`, `APCA_PAPER_SECRET_KEY` in `production/.env.paper`
- **Base URL**: `https://paper-api.alpaca.markets` (routed automatically by `TradingClient(paper=True)`)
- **Provides**: Real-time paper order fills (no delay, unlike Tradier sandbox)
- **Starting balance**: $100k default. No API to set custom amount — use `PAPER_STARTING_BALANCE=5000` env var so runners size positions as if $5k capital.
- **Last verified working**: 2026-06-17 (paper balance: $97,797.60)
- **Key history**:
  - Old keys (PK...) — generated earlier, failed with 401. Regenerated 2026-06-17.
  - Current keys — `PK5KVPQMDVQRKK3NDASTQYRTB7` + secret. Working as of 2026-06-17.
- **Scripts that use it**:
  - `production/trading/live_scalp_runner.py` — paper order execution
  - `production/trading/live_vwap_runner.py` — paper order execution
  - `production/trading/broker/alpaca.py` — `AlpacaBroker(paper=True)`
- **NOTE**: Alpaca paper reset button was removed in 2023-2025 UI redesign. No API endpoint. See `research/reset_paper_account.py`.

### Tradier (Data Feed — Real-time Quotes + Premarket Timesales)
- **Account**: Dual-token setup — production token for real-time data, sandbox token for paper orders (15-min delayed, blind premarket)
- **Env vars**: `TRADIER_PAPER_TOKEN`, `TRADIER_ACCOUNT_ID`, `TRADIER_PRODUCTION_TOKEN` in `production/.env.paper` + SOPS-encrypted `production/.env.render`
- **Provides**:
  - Real-time quotes (batched) — via production token
  - **Premarket timesales** — production token; ONLY source with same-day premarket volume data (Alpaca returns volume=0). Used as HybridRelVol numerator.
  - **NOT used for orders anymore** — switched to Alpaca paper 2026-06-17
  - **NOT**: minute/hourly historical bars (timesales returns null without funded brokerage)
- **Critical for rel-vol**: `HybridRelVol` uses Tradier production timesales as numerator (real-time cumulative volume) + Alpaca 30-day historical minute bars as denominator. Without Tradier production token, rel-vol falls back to 10.0× default.
- **Last verified working**: 2026-07-01 (premarket timesales via production token; HybridRelVol live-tested)
- **MUST set `TRADIER_PRODUCTION_TOKEN` on Render** — sandbox token has no real-time premarket data
- **Scripts that use it**:
  - `production/trading/rel_vol_live.py` — `HybridRelVol._numerator()` (timesales)
  - `production/trading/broker/tradier.py` — TradierDataFeed (fallback, `BROKER=tradier`)

### Polygon / Massive.com (Inactive)
- **Account**: Basic tier (free)
- **Env vars**: `POLYGON_API_KEY` in `production/.env.paper`
- **Key**: `gqXFwv...`
- **Provides**:
  - Daily bars via grouped endpoint — works
  - Minute bars — **NOT on Basic tier** (returns 0 results)
  - Ticker reference data — works
- **Status**: Key valid but Basic tier too limited for minute bars. Was used for Mar 7-15 2026 gap fill.
- **To unlock minute bars**: Starter plan = $29/mo
- **Script**: `production/data/backfill/backfill_polygon.py`

### NASDAQ Trader FTP (Symbol Universe)
- **URL**: `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt`
- **Provides**: Full list of all US exchange-listed symbols, updated daily
- **Auth**: None required (public)
- **Returns**: ~7,200 non-ETF stocks with ticker <= 5 chars
- **Used by**: `live_scalp_runner.py` `_fetch_nasdaq_symbols()` for daily universe refresh

### Neon PostgreSQL (Rel-Vol Baseline + Float Data — primary live store)
- **Account**: Free tier (neondb_owner)
- **Env vars**: `NEON_CONNECTION_STRING` in SOPS-encrypted `production/.env.render` (Render) + `production/.env.render.dec` (local, via `decrypt-local.sh`)
- **Tables**:
  - `rel_vol_baselines` — 235+ symbols, `float_shares` column; new gappers auto-inserted by `fetch_missing_floats()`
  - `active_symbols` — 2,300+ symbols accumulated from live sessions; new gappers auto-registered
  - `pipeline_runs` — daily 4:30 PM ET runs logged
  - `session_bars`, `session_logs`, `session_news`, `session_runs` — live session persistence
  - `live_trades` — completed trade records
  - `stock_candles_live_1m`, `stock_news_live` — live-captured minute bars + news
- **Populated by**:
  - `production/data/live_capture/build_baseline_cloud.py` via GitHub Actions (`rel-vol-baseline.yml`, daily 4:30 PM ET) — bulk refresh
  - `production/trading/rel_vol_live.py` `fetch_missing_floats()` — live yfinance fallback for new gappers (writes back to Neon)
- **Used by**: `production/trading/rel_vol_live.py` `_fetch_from_neon()` — primary source on Render
- **Last verified working**: 2026-07-01 (float write-back tested with SVRE, CELZ, JBDI, GVH, JEM)
- **Notes**: Float data two-tier: weekly bulk refresh (yfinance, `FLOAT_STALE_DAYS=7`) for known symbols + live per-scan `fetch_missing_floats()` for brand-new gappers. `NEON_CONNECTION_STRING` lives in SOPS-encrypted `.env.render`; falls back to GitHub JSON if absent.

### Finnhub (News — primary)
- **Account**: Free tier
- **Env vars**: `FINNHUB_API_KEY` in `.env`
- **Provides**: Real-time news for live runners
- **Last verified working**: 2026-06-23 (primary waterfall slot)

### yfinance (Float Data — live fallback)
- **Account**: No API key required (scrapes Yahoo Finance)
- **Provides**: `floatShares` for individual tickers via `yf.Ticker(sym).info`
- **Rate limit**: ~1.2s/request (self-imposed sleep to avoid throttling)
- **Used by**:
  - `production/data/live_capture/build_baseline_cloud.py` — weekly bulk float refresh
  - `production/trading/rel_vol_live.py` `fetch_missing_floats()` — live per-scan fallback for new gappers
- **Last verified working**: 2026-07-01 (SVRE, CELZ, JBDI, GVH, JEM all resolved)
- **Gotcha**: Some tickers return `None` for `floatShares` (very new IPOs, SPACs). These are silently skipped; `max_float` filter treats them as `None` → no-op (passes through).

### Marketaux (News — REMOVED 2026-06-23)
- **Status**: ⚫ REMOVED from `news_fetcher.py` waterfall. Rate limit was always exhausted; each timeout = 5s × 50 symbols = 4+ min wasted per scan cycle.
- **Commit**: `0efa80a`

### SOPS + age Encryption (Secrets Management)
- **Config**: `.sops.yaml` in repo root (age public key)
- **Encrypted file**: `production/.env.render` — single source of truth for ALL secrets (DB, API keys, tokens)
- **Render**: `decrypt-and-start.sh` decrypts at boot using `SOPS_AGE_KEY` env var (the ONLY secret manually set on Render)
- **Local**: `production/scripts/decrypt-local.sh` → `production/.env.render.dec` (gitignored)
- **Age key location**: `C:\Users\joelb\AppData\Roaming\sops\age\keys.txt` (local); `SOPS_AGE_KEY` env var (Render)
- **Workflow**: Edit `.env.render` plaintext → `sops -e -i production/.env.render` → commit → deploy. Never touch Render dashboard for secrets.
- **Last verified working**: 2026-07-01 (local decrypt + Render boot tested)

## DB Coverage (as of 2026-06-09)

| Table | Latest Data | Notes |
|-------|-------------|-------|
| `stock_candles_1m` | 2026-03-13 | Minute bars 8am-12pm ET |
| `stock_candles_1h` | 2026-03-13 | Hourly bars 4am-8am ET |
| `stock_candles_1d` | 2026-03-13 | Daily bars |
| `stock_news` | ~2026-05-27 | 17K+ articles, backfilled for gapper symbols |
| `daily_gappers` | 2026-03-13 | 84K rows, precomputed gap% cache |
| `rel_vol_cum_cache` | 2026-02-18 | 235M rows, cumulative volume by minute |

**Gap to fill**: 2026-03-14 through 2026-06-09 (~60 trading days)

## Backfill History

| Date | Range | Source | Script | Notes |
|------|-------|--------|--------|-------|
| ~2026-05-15 | 2021-01-04 to 2026-03-13 | Alpaca (key AK42) | backfill_optimized.py | Full 5-year backfill for scalp optimizer |
| ~2026-05-27 | 2021-2026 gapper days | Alpaca (key AK42) | backfill_news.py | 16,724 articles for daily_gappers symbols |
| ~2026-05-27 | 2021-01-04 to 2026-02-18 | DB computation | manual SQL | rel_vol_cum_cache built from stock_candles_1m |
| 2026-03 | 2026-03-07 to 2026-03-15 | Polygon (Basic) | backfill_polygon.py | Small gap fill, daily bars only |

## Lessons Learned

1. **Alpaca key regeneration kills old keys instantly.** Never regenerate unless old key is compromised.
   If you need a second key, create it alongside the existing one (if Alpaca allows).

2. **Alpaca free tier DOES provide historical minute bars.** The confusion on 2026-06-09 was testing
   on non-trading days (Saturday, etc.). Always use `trading_calendar.get_trading_days()` to pick
   valid dates for testing.

3. **Tradier sandbox = 15-min delayed everything.** Both data feed and order execution are delayed.
   Set `sandbox=True` on BOTH `TradierBroker` and `TradierDataFeed` for uniform delay.

4. **Static symbol lists go stale.** `stocks_in_price_range.txt` was 3 months old by June 2026.
   Now using NASDAQ trader FTP for daily refresh + Tradier live quotes for price filter.

5. **Alpaca `get_quotes()` returns `prev_close=0.0`** (2026-06-17). The latest-quote endpoint has no prev_close field. Both runners must call `get_prior_closes()` first and patch the QuoteResult. If you forget, every symbol fails `q.prev_close <= 0` → 0 gappers found → no trades.

6. **Alpaca paper reset button is gone** (removed 2023-2025). `POST /v2/account` returns 404. All new paper accounts start at $100k. Use `PAPER_STARTING_BALANCE=5000` in env for realistic position sizing. Contact Alpaca support if you need the actual balance changed.

7. **Alpaca live + paper accounts can run simultaneously.** Each `TradingClient` is independent. Use live keys (`APCA_API_KEY_ID`) for data API; separate paper keys (`APCA_PAPER_KEY_ID`) for `TradingClient(paper=True)`. Regenerating one set does NOT affect the other.

8. **Tradier sub-penny rejection (error 42210000).** Limit prices must be rounded to exactly 2 decimal places before calling `place_limit_buy()`. Floating-point arithmetic (e.g. `2.7478999...`) is silently truncated by the broker and rejected. Fix: `entry_price = round(entry_price, 2)` in all 3 runners (added 2026-06-23, commit `0efa80a`).

9. **Render uses `production/requirements-deploy.txt`, not root `requirements.txt`.** Any new Python dependency needed on Render (psycopg2, yfinance, etc.) must be added to `production/requirements-deploy.txt`. The root file is for local dev only. This caused psycopg2 + yfinance to silently fail on Render for weeks.

10. **Render ephemeral disk wipes on every deploy.** Session state JSON, bar captures, and logs are lost. Always run `session_report.py` and pull bars BEFORE any deploy. The `session-capture.yml` GitHub Action (12 PM ET daily) mitigates this but only captures one snapshot per day.

11. **Alpaca real-time feed returns volume=0 for premarket** (2026-06-30). The iex feed on the free tier has no premarket volume data. Cumulative volume is always 0 → rel-vol ratio always hits the 10.0× fallback cap → every stock looks like a monster. Root cause of "always 10.0×" bug. Fix: use Tradier production timesales for the numerator (only source with same-day premarket volume). See `HybridRelVol` in `rel_vol_live.py`.

12. **Alpaca stop-sell rejection (error 42210000)** when price crashes past stop trigger before the order reaches the broker (2026-07-01). Alpaca won't auto-convert to market; it just rejects. On fast-crashing small-caps, the gap between entry-fill and stop-placement (several seconds for order poll + fill confirmation) is enough. Fix: catch rejection → immediately place market sell. See `live_scalp_runner.py` and `live_vwap_runner.py`.

13. **SOPS `--input-type dotenv --output-type dotenv` required for .env files** (2026-07-01). Default `sops -d` assumes JSON → `Error unmarshalling input json`. Must explicitly specify dotenv format for `.env.render`. The decrypt-local.sh script handles this automatically.

14. **yfinance `floatShares` returns None for some tickers.** Very new IPOs, SPACs, and some micro-caps have no float data on Yahoo Finance. `fetch_missing_floats()` silently skips these; the `max_float` filter treats `None` as pass-through (no-op). This is intentional: better to trade without float data than to silently drop a valid candidate.
