# Pre-registration: fade liquid gap-ups that have no news (fresh years 2016-2020)

_Written 2026-10-23, before any data for 2016-2020 was pulled. Committed before the data script runs.
One look at the sealed result; no changes afterwards._

## Why this test

- The one result that keeps repeating in this project: stocks moving on real news beat stocks moving without news.
  In liquid stocks (`docs/PREREG_2026_10_LIQUID_NEWS_GAP.md`, 2021-2026) news gap-ups beat no-news gap-ups on the
  same day by +0.40% (CI +0.07% to +0.70%), and both groups lost in absolute terms when bought.
- If no-news gap-ups lose when bought, the tradeable side may be the **short**: a gap with no catalyst behind it
  fades. Liquid stocks keep costs low and are usually easy to borrow; the short-sale restriction (triggered by a 10%
  drop) does not apply to stocks that gapped up.
- The idea came from 2021-2026 data, so the decision uses **2016-2020 only**, years never pulled or looked at for
  liquid gap-ups or their news.

## Rule (fixed)

**Universe each day**
- The same US common-stock list as `liquid_gap_orb_test.py` (`universe()`: Alpaca active and inactive assets,
  NYSE/Nasdaq/NYSE American, plain tickers, ETFs/funds excluded).
- Prior close between $10 and $500.
- Average daily dollar volume (close x volume) over the prior 20 trading days of at least $50M.
- Gap = official open (the daily bar open) / prior close - 1, from +4% to +60% (above +60% excluded as likely
  split artifacts).

**No news**
- No article classified `catalyst` by `article_type(headline, n_symbols)` in `premarket_news_test.py` (unchanged),
  from Alpaca news (Benzinga) tagged to the symbol, created between 16:00 ET the prior trading day and 09:29:59 ET.
  Same definition as the liquid news gap test. Stock-days with only roundup/reaction articles count as no news.

**Trade**
- Short at the open of the first one-minute bar from 09:31 to 09:35. No bar in that window: no trade.
- Cover at the close of the last one-minute bar at or before 11:59 (must be after entry). No stop.
- Every qualifying stock-day trades; no daily cap.
- Return = -(cover / entry - 1) minus costs.

**Costs:** 0.15% per side primary; 0.30% per side robustness. Borrow assumed free (intraday, liquid names).
**Period (decides):** 2016-01-04 to 2020-12-31.
**Statistics:** mean net return per trade; 95% CI from a bootstrap that resamples days (stocks on the same day are
correlated).
**Data:** Alpaca SIP daily bars and 09:30-16:00 one-minute bars (raw prices), Alpaca news.

## Pass bar (all five required, 2016-2020)

- (a) at least 1,000 trades;
- (b) mean net return per trade above 0 at 0.15% per side, day-clustered 95% CI lower bound above 0;
- (c) positive mean in at least 4 of the 5 years;
- (d) mean net return still above 0 at 0.30% per side;
- (e) not carried by outliers: the mean after dropping the best 1% of trades is still above 0.

Any failure closes this idea.

## Report-only (never used to decide)

- Cover at 10:30 and at 15:59 instead of 11:59.
- A stop 5% above entry (honest fills: a bar that opens through the stop fills at its open).
- News gap-ups traded with the same short rule, and the same-day paired difference no-news minus news.
- Gap 4-10% vs above 10%; per-year means; share of gap-ups with news per year (news-coverage check).
- 2021-2026 with the same rule (the period the idea came from; in-sample, shown for context only).

## Known limits

Benzinga coverage in Alpaca news may be thinner in 2016-2018, so some "no news" stock-days may have had news
elsewhere; the per-year news share is reported so this can be judged. Some delisted tickers are missing from Alpaca's
asset list (mild survivorship). Shares assumed borrowable at no fee.

## Result (2026-10-23, one look, rule unchanged)

`python research/analysis/scripts/no_news_gap_fade_test.py evaluate` (output saved under
`research/analysis/outputs/no_news_fade/`). 10,890 qualifying gap-ups on 1,106 days, 7,032 without a catalyst
article, 7,007 tradable. Data check: 0 look-ahead articles, 100% minute-bar coverage. 2020 dominates the sample
(5,831 of 7,007 trades) and has low news coverage (22% catalyst share vs 52-75% in 2016-2019).

| Criterion | Result | |
|---|---|---|
| (a) >= 1,000 trades | 7,007 | PASS |
| (b) mean net > 0 at 0.15%/side, CI lower bound > 0 | +0.285%, **CI -0.92% to +1.61%** | FAIL |
| (c) positive in >= 4 of 5 years | 4 (2016 -0.19%, 2017 +0.01%, 2018 +0.66%, 2019 +0.12%, 2020 +0.31%) | PASS |
| (d) mean net > 0 at 0.30%/side | -0.015% | FAIL |
| (e) > 0 without the best 1% of trades | +0.121% | PASS |

**VERDICT: FAIL.** The average is positive but statistically indistinguishable from zero: stocks gapping on the same
day move together, so the day-clustered CI is wide, and the edge disappears at 0.30%/side. Report-only: news
gap-ups shorted the same way -0.17%; same-day paired no-news minus news +0.28% (CI -0.03% to +0.59%), the
news effect again in the same direction but not significant here; gap above 10% +0.97% (CI -0.92% to +3.38%, 480
trades); cover at 15:59 -0.65%; 2021-2026 in-sample +0.03%. This idea is closed as specified. Post-hoc note,
NOT actionable: no-news gaps above 10% were positive in both periods (+0.97% here, +1.48% in 2021-2026); that is a
new hypothesis needing its own pre-registration and fresh data.
