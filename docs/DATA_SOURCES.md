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

### Tradier (Data Feed Only — Real-time Quotes)
- **Account**: Production token for real-time quotes; paper token for sandbox orders (no longer used for orders)
- **Env vars**: `TRADIER_PAPER_TOKEN`, `TRADIER_ACCOUNT_ID`, `TRADIER_PRODUCTION_TOKEN` in `production/.env.paper`
- **Provides**:
  - Real-time quotes (batched) — via production token
  - **NOT used for orders anymore** — switched to Alpaca paper 2026-06-17
  - **NOT**: minute/hourly historical bars (timesales returns null without funded brokerage)
- **Last verified working**: 2026-06-17 (quotes via production token)
- **Scripts that use it**:
  - `production/trading/broker/tradier.py` — TradierDataFeed (still available as fallback, `BROKER=tradier`)

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
