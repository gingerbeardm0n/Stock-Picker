# Pre-registration: "Stocks in Play" 5-minute opening-range breakout (published-strategy replication)

_Written 2026-10-21, before any data for this test was pulled. Committed before the data scripts run.
One look at the results; no changes afterwards._

## Why this test

- Joel is continuing jTrader as a research project (2026-10-20). The Ross Cameron line taught us that his
  measurable edge is picking the stock "in play", and that small-cap costs eat everything.
- The closest **published** relative of that idea is Zarattini, Barbon & Aziz (2024, SSRN; a "Stocks in Play"
  opening-range-breakout strategy, reported Sharpe about 2.8 over 2016-2023). Rules here are taken from
  secondary summaries (CXO Advisory, QuantifiedStrategies, an MQL5 replication); the paper itself was not read.
- Known weakness: the paper charges commission only, with no spread or slippage, and had no out-of-sample
  period. An independent replication on index CFDs found the gross results reproduce but net is about zero.
  **This test adds honest costs and a post-publication period (2024-01 to 2026-10).**
- Liquid stocks keep costs low (measured median quoted spread at entry on liquid gap-ups: 0.17%).

## Rule (fixed)

**Universe each day** (using only data known before 09:30, except where noted):
- The same US common-stock list as `liquid_gap_orb_test.py` (NYSE/Nasdaq/NYSE American, Alpaca active and
  inactive assets, ETFs/funds and non-plain tickers excluded).
- Opening price above $5 (the 09:30 open, known at the open).
- Average daily volume over the prior 14 trading days of at least 1,000,000 shares.
- 14-day ATR (prior 14 trading days, true range on raw daily bars) above $0.50.

**Stocks in play**
- Opening range = the 09:30-09:34 one-minute bars (5 minutes; at least 3 bars).
- Relative volume = opening-range volume divided by the average opening-range volume over the prior 14 trading
  days (at least 10 of them available).
- Keep stocks with relative volume of 1.0 or more, then the 20 highest relative volumes that day.

**Direction and entry**
- Opening-range close above its open: long. Below: short. Equal: no trade.
- Long: buy-stop at the opening-range high + $0.01; short: sell-stop at the opening-range low - $0.01.
  Live from 09:35 to 15:55. Fill = the trigger bar's open if it gapped through the level, else the level.

**Exit**
- Stop at 10% of the 14-day ATR from the entry price, checked from the bar after entry, honest fills (a bar that
  opens through the stop fills at its open; otherwise the worse of the stop and the next bar's open).
- Otherwise exit at the close of the last bar at or before 15:59.

**Costs:** 0.15% per side primary (spread + slippage + commission on liquid names); 0.30% per side robustness.
Report-only: the paper's own assumption ($0.0035 per share commission only).
**Counting:** every qualifying trade counts. Results are reported per trade in R (risk = 10% of ATR) and in percent.
**Period:** 2016-01-04 to 2026-10-16. Post-publication window: 2024-01-02 to 2026-10-16.
**Data:** Alpaca SIP daily bars, 09:30-09:34 one-minute bars for every eligible stock-day (for relative volume),
and 09:30-16:00 one-minute bars for the 20 selected stocks each day. Raw prices; gaps above +60% or below -40%
vs the prior close are excluded as likely split artifacts (decided now, before any data).

## Pass bar (all five required)

- (a) at least 1,000 trades;
- (b) mean net R per trade above 0 at 0.15% per side over the full period, day-clustered 95% CI lower bound above 0;
- (c) mean net R above 0 in the post-publication window (2024-01 to 2026-10);
- (d) mean net R still above 0 at 0.30% per side over the full period;
- (e) not carried by outliers: the full-period mean after dropping the best 1% of trades is still above 0.

Any failure closes this idea.

## Report-only (never used to decide)

Long-only and short-only splits; per-year means; the paper's commission-only cost assumption (a gross-replication
check); top 10 instead of top 20; exits by type.

## Known limits

Rules come from secondary sources. Some delisted tickers are missing from Alpaca's asset list (mild
survivorship). Short trades assume shares were borrowable at no fee (liquid names, usually true).
