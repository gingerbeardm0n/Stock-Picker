# Corporate-Action / Reverse-Split Detection Survey (2026-07-02)

**Motivation:** JBDI (Jun 30) showed up as a huge "gap" that was actually a
reverse-split price artifact — scanner scored and traded it (−$36.52).
Memory: `memory/corporate_actions_filter.md`. Same anti-overfit rule applies:
signal must be **backtestable** against the 2021–2025 gapper universe before it
ever gates a live trade (`memory/live_filter_backtest_challenge.md`).

## Why phantom gaps happen

`gap_pct = (open − prior_close) / prior_close` using the raw daily bar. On a
1:N reverse split day, prior_close is pre-split (e.g. $0.50), the quote is
post-split ($5.00) → gap looks like +900%. There is no real buying — usually
the opposite (reverse splits signal distress; they typically fade).

## Source comparison

| Source | What | Cost | Same-day usable? | History | Notes |
|---|---|---|---|---|---|
| **Alpaca Corporate Actions API** (`/v2/corporate_actions/announcements`) | Splits (incl. reverse via old_rate/new_rate), dividends, mergers | Included with our existing keys (Trading API; verify with live call) | Ingested ~the trading day after declaration; ex_date known **in advance** → yes for premarket check | Queryable date range | **Best fit — we already have credentials** |
| **Polygon `/v3/reference/splits`** | Split events + execution_date, split_from/to | Basic (free) tier — reference data generally included; rate-limited 5 req/min | Yes (execution_date filterable) | Deep | Known dupes/data-quality issues (216 same-day dupes reported) |
| **NASDAQ daily list / press pages** | Upcoming splits | Free (scrape) | Yes | Poor for bulk | Fragile scraping; last resort |
| **Financial Modeling Prep** | Splits calendar/history API | Free tier limited | Yes | OK | Redundant with the above |
| **Price-only heuristic (no vendor)** | Detect artifact from our own DB | Free | Yes | Full 2016–2026 | See below — strongest backtest story |

## The cheap heuristic (recommended first line)

A reverse-split phantom gap has a distinctive fingerprint visible in data we
already have:

1. **Absurd gap%** — JBDI-style gaps are far outside the organic distribution
   (organic gap-and-run setups are ~10–100%; split artifacts are often 300–1000%+).
   Our sim already caps at 1000%, which is a blunt version of this.
2. **Volume does not confirm** — a real 300% gapper prints massive premarket
   volume; a split artifact opens on normal-to-thin volume (rel_vol low or the
   Tradier premarket tape nearly empty).
3. **Round split ratios** — prior_close × N ≈ open for small integer N
   (5, 10, 20, 25, 50): `abs(open/prior_close − round(open/prior_close)) < tol`.
4. **Share-count discontinuity** — daily-bar volume collapses ~by the split
   ratio versus the trailing average.

Composite rule sketch: flag if `gap_pct > X` AND (`rel_vol < Y` OR ratio ≈ round N).
Thresholds to be fit on train years only.

## How to backtest against the 2021–2025 gapper universe

1. Pull Polygon splits history (free tier, ratelimited — one-time bulk pull) →
   `stock_splits(symbol, execution_date, from, to)` table. Cross-check a sample
   against Alpaca announcements to catch Polygon's known dupes.
2. Join to the gapper universe: label every gapper-day that coincides with a
   reverse-split execution_date = ground truth positives.
3. Run the heuristic over all gapper-days; report precision/recall against the
   labels. Target: high precision (never veto a real gapper), recall secondary.
4. Then run the sims with flagged days EXCLUDED and compare P&L deltas on
   train (2021–23) → select (2024) → sealed 2025. Only ship if the exclusion
   is at worst P&L-neutral on organic setups.
5. Live: implement as a **logged tag first** (e.g. `suspected_split_artifact`)
   for 2+ weeks before it ever blocks a candidate.

## Recommendation

- **Detection at scan time:** query Alpaca corporate-actions announcements for
  today's ex-date reverse splits during the premarket scan (we already hold the
  keys; one API call, symbols cross-checked against candidates) — belt.
- **Heuristic as fallback:** the price/volume fingerprint catches anything the
  announcement feed misses (OTC oddities, data lag) — suspenders.
- **Backtest first** exactly as above; no live gating until validated.

Sources: [Alpaca Corporate Actions API announcement](https://alpaca.markets/blog/introducing-corporate-actions-api-announcements/) ·
[Alpaca corporate actions reference](https://docs.alpaca.markets/reference/corporateactions-1) ·
[Polygon splits endpoint](https://polygon.io/docs/stocks/get_v3_reference_splits) ·
[Polygon split data-quality issue #311](https://github.com/polygon-io/issues/issues/311)
