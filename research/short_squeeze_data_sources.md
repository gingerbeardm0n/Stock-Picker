# Short-Squeeze Data Source Survey (2026-07-02)

**Motivation:** JEM (Jun 30) scored #1 on the scalp scanner but was a short-squeeze
setup, not a momentum gap — wrong pattern, bad trade. Before any squeeze
detection/filter can be built, we need **backtestable historical data**
(anti-overfit rule: never add a qualitative filter validated only against
individual bad trades — see `memory/live_filter_backtest_challenge.md`).

## What a squeeze signal needs

- **Short interest** (% of float) — how crowded the short side is.
- **Cost to borrow / borrow availability** — how squeezed shorts already are.
- **Fails-to-deliver** — secondary confirmation of borrow stress.
- All of the above **as-of historical dates** (point-in-time), 2021–2025, to
  join against our gapper universe in TimescaleDB.

## Source comparison

| Source | What | Cost | Frequency | History | API | Backtestable? |
|---|---|---|---|---|---|---|
| **FINRA Equity Short Interest** | SI shares/ratio, all listed + OTC | Free | Bi-monthly (settlement ~2wk lag) | Archives to 2014 | Yes — `api.finra.org/data/group/otcMarket/name/EquityShortInterest` (CSV/JSON) + file downloads | **Yes — best free option** |
| **SEC Fails-to-Deliver** | Daily FTD count/value per CUSIP | Free | Published twice-monthly, ~2wk lag | Years of archives (CSV zips) | Bulk file download | Yes (supplementary) |
| **FINRA Short Sale Volume (daily)** | Daily short-sale volume by symbol | Free | Daily | Years | File download | Yes, but often misinterpreted — short VOLUME ≠ short INTEREST |
| **Ortex** | Intraday SI estimates, cost-to-borrow, utilization | $$$ (institutional; API on paid tiers) | Real-time/daily | Deep | Yes (docs.ortex.com, Python SDK) | Yes but expensive |
| **Fintel** | SI, borrow rates, squeeze score | $ (subscription; API access unclear/limited) | Daily | Charts yes; bulk history via API weak | Partial | Marginal |
| **ChartExchange** | Borrow data, short volume, bulk datasets | Free tier + paid | Daily | Some bulk historical sets | Yes (v1 API) | Maybe — worth a test pull |
| **IBKR SLB / shortable file** | Live borrow rate + availability | Free w/ account | Intraday snapshots | Only if you archive it yourself going forward | FTP-style file + TWS API | Not retroactively |

## Recommendation

1. **Start with FINRA bi-monthly short interest (free).** Pull the full 2021–2025
   archive, load into a `short_interest` table keyed (symbol, settlement_date),
   compute SI%-of-float using our existing float data. Coarse (bi-monthly) but
   point-in-time correct and covers our whole backtest window at zero cost.
2. **Add SEC FTD archives** as a second free feature (same join pattern).
3. **Skip Ortex/Fintel for now** — daily-resolution borrow data would be nicer,
   but cost is unjustified before the coarse signal proves ANY predictive value.
4. **Optionally start archiving IBKR/ChartExchange borrow snapshots daily now**
   so a finer-grained dataset exists a year from now.

## Proposed experiment — TAG-FIRST, never filter-first

1. Backfill FINRA SI for every symbol-day in the 2021–2025 gapper universe
   (most recent settlement date ≤ trade date — no lookahead).
2. Tag each simulated scalp/VWAP trade with `si_pct_float` bucket
   (<5%, 5–15%, 15–30%, >30%) + FTD z-score.
3. Compare P&L / win-rate / PF across buckets on the TRAIN years (2021–23),
   confirm on 2024, only then look at sealed 2025.
4. Only if high-SI buckets show materially worse expectancy does a filter (or a
   score penalty) get proposed — and it ships as a **tag logged live for 2+ weeks**
   before ever gating a trade.

Sources: [FINRA Equity Short Interest](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/data) ·
[FINRA API metadata (PDF)](https://www.finra.org/sites/default/files/Equity_Short_Interest_Data_File_Download_API.pdf) ·
[FINRA Short Sale Volume](https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data) ·
[SEC Fails-to-Deliver](https://www.sec.gov/data-research/sec-markets-data/fails-deliver-data) ·
[Ortex docs](https://docs.ortex.com/) · [ChartExchange API](https://chartexchange.com/api/v1/docs/) ·
[IBKR Short-Securities Availability](https://www.interactivebrokers.com/en/trading/short-securities-availability.php)
