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
