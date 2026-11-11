# Pre-registration: multi-day drift after news gap-ups (enter at the close, hold days)

_Written 2026-11-11, before any multi-day outcome data was pulled. Committed before the data script exists.
One look at the result; no changes afterwards._

## Why this test

- `docs/STEP_BACK_2026_11.md`: ten intraday tests were all about zero before costs. The one finding that held
  everywhere is that stocks moving on real news behave better than stocks moving without news, but it was only
  ever tested **within the day**, where costs eat it.
- Published work says the news effect plays out over **days to weeks**: stocks with news keep drifting, stocks that
  jump without news reverse (Chan, JFE 2003; Jiang, Li & Wang, "News Momentum"; post-earnings-announcement drift,
  strongest in small, less-covered stocks). Over a multi-day hold a round trip costs a small fraction of the move.
- Entering at the close of the news day is slow and fully autonomous: no speed race, no premarket spread.

**Prior exposure (honest):** earlier tests looked at news gap-ups **within the gap day** (Ross tests, liquid ORB
test). Returns **after** the gap day's close have never been pulled or looked at in this project. The entry here
is the gap day's close, so nothing seen before overlaps the outcome window.

## Hypothesis

US stocks that gap up at least 5% at the open on fresh company-specific news, bought at that day's close, keep
rising over the next 5 trading days, by enough to profit after realistic costs and beyond the market's own move.

## Rule (fixed)

**Universe each day** (information available before the gap day's open):
- Same US common-stock list as `liquid_gap_orb_test.py` (`universe()`: Alpaca active and inactive assets,
  NYSE/Nasdaq/NYSE American, plain tickers, ETFs/funds excluded).
- Prior close between $2 and $500.
- Average daily dollar volume (close x volume) over the prior 20 trading days of at least $5M.

**Event (gap day D)**
- Gap: daily open of D at least 5% above the prior close, and at most 300% above it (larger gaps are treated as data
  errors).
- Catalyst: at least one Alpaca news article (Benzinga) tagged to the symbol, created from 16:00 ET on the prior
  trading day to 09:29:59 ET on D, classified `catalyst` by `article_type(headline, n_symbols)` in
  `premarket_news_test.py` (unchanged).

**Trade**
- Long only. Entry: official close of D. Exit: close of the 5th trading day after D (D+5).
- If the stock stops trading before D+5, exit at its last available close.
- One open position per symbol: an event for a symbol already held is skipped. No daily cap; every event trades.
- Return: exit / entry - 1, minus 2 x cost. Market-adjusted return: that net return minus SPY's close-to-close
  return over the same days.

**Costs:** 0.25% per side primary (closing auction / close-to-close, mixed liquidity); 0.50% per side robustness.
**Prices:** Alpaca SIP daily bars, split-adjusted (dividends ignored).
**Period (decides):** entry days 2016-01-04 to 2026-10-23.
**Statistics:** mean net return per trade; 95% CI from a bootstrap that resamples **calendar months** (holds overlap
across days, so months are the cluster).

## Pass bar (all seven required)

- (a) at least 1,000 trades;
- (b) mean net return above 0 at 0.25% per side, month-clustered 95% CI lower bound above 0;
- (c) mean market-adjusted net return above 0, CI lower bound above 0 (the gain is not just the market);
- (d) mean net return above 0 in both halves: 2016-2020 and 2021-2026;
- (e) positive mean in at least 6 of the 11 calendar years;
- (f) mean net return still above 0 at 0.50% per side;
- (g) not carried by outliers: the mean after dropping the best 1% of trades is still above 0.

Any failure closes this idea as specified.

## Report-only (never used to decide)

- Holds of 1 and 20 trading days (20-day drops entries without 20 days of data).
- No-news gap-ups (no article of any type in the window) under the same rule, and the news-minus-no-news gap
  (the Chan replication). Short no-news gap-ups for 5 days.
- Gap-downs of 5% or more on catalyst news, short, 5 days.
- Gap thresholds 10% and 20%.
- Tiers: liquid ($10-$500, 20-day dollar volume >= $50M); Ross-style ($1-$20).
- Entry at the open of D+1 instead of the close of D.
- Per-year means; long vs market-adjusted; median and share positive.

## Known limits

Assumes the closing auction fills at the official close. `created_at` is Benzinga's publish time; some news is
earlier. Some delisted tickers are missing from Alpaca's asset list (mild survivorship, flatters longs). Exiting a
delisted stock at its last close can miss a final drop. Split adjustment depends on Alpaca's corporate-action data.
Dividends ignored (small over 5 days).

## Addendum (implementation, decided 2026-11-11 before any outcome data was pulled)

- Price and dollar-volume filters use **raw** (as-traded) daily bars, which is what a trader saw that morning.
  Gap and all returns use **split-adjusted** bars, so a split never looks like a gap or a return.
- News is reused from the intraday test's table `ind_news`: every article created from 16:00 ET the prior trading
  day to 15:00 ET, for every symbol-day with raw prior close $1-$500 and 20-day dollar volume >= $2M (coverage
  verified complete in that test). Only articles created before 09:30:00 ET on D are used. This table holds no
  prices, so no outcome has been seen. Consequence: the report-only Ross-style tier ($1-$20) also needs 20-day
  dollar volume >= $2M.
- "Stops trading before D+k" = the symbol's last daily bar is more than 7 calendar days before the end of the fetched
  data; otherwise a missing D+k bar means the data ends, and that trade is dropped for that hold.
- Overlap: an event on day index k is skipped if the symbol already has a kept trade entered at index j with
  k <= j + hold.

## Result (2026-11-11, one look, rule unchanged)

`python research/analysis/scripts/multiday_news_drift_test.py evaluate`. `check` first: 0 candidate days missing news,
23,070 primary events (997-3,391 per year), every one with a 5-day exit, 5 exits at a last close. After the
one-position-per-symbol rule: **21,914 trades**. Output saved under `research/analysis/outputs/multiday_news/`.

| Criterion | Result | |
|---|---|---|
| (a) >= 1,000 trades | 21,914 | PASS |
| (b) mean net > 0 at 0.25%/side, CI lower bound > 0 | **-0.474%** (CI -0.914% to -0.027%) | FAIL |
| (c) market-adjusted mean > 0, CI lower bound > 0 | -0.911% (CI -1.214% to -0.588%) | FAIL |
| (d) mean > 0 in 2016-2020 and 2021-2026 | -0.231% / -0.603% | FAIL |
| (e) positive in >= 6 of 11 years | 1 (2016) | FAIL |
| (f) mean net > 0 at 0.50%/side | -0.971% | FAIL |
| (g) > 0 without the best 1% of trades | -1.163% | FAIL |

**VERDICT: FAIL.** Stocks that gap up 5%+ on catalyst news do not drift up after the gap day's close: gross +0.03%
over 5 days, and about -0.4% versus SPY before costs (they lag the market). Report-only: every hold loses net
(1 day -0.57%, 20 days +0.55% raw but -1.02% market-adjusted); bigger gaps are worse (10%+: -0.87%, 20%+: -2.04%);
liquid tier -0.51%, Ross-style tier -0.80%; entering at the next open -0.55%; shorting catalyst gap-downs -0.50%,
shorting no-news gap-ups -0.25% (CI spans 0). The news-vs-no-news difference shows up again (+0.28% over 5 days)
but both sides lose. The Chan (2003) drift does not exist in this universe in 2016-2026. This closes multi-day
news drift as specified.
