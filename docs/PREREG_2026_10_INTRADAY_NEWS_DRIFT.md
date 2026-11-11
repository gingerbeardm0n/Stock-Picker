# Pre-registration: drift after catalyst headlines that break during the trading day (delayed entry)

_Written 2026-10-28, before any intraday-headline data was pulled. Committed before the data script exists.
One look at the result; no changes afterwards._

## Why this test

- The one result that keeps repeating in this project: stocks moving on real news beat stocks moving without news.
  Every test so far used **premarket** news and traded the **open**. Joel's view: news moves a stock when it lands,
  at the open for overnight news, or whenever it drops during the session. News that breaks during the session has
  never been tested here.
- The Polymarket-bot review (2026-10-28) showed that pure speed edges belong to the fastest bots and get closed.
  So this test enters **after a deliberate delay** (the minute after the headline minute ends, so 1-2 minutes after
  the headline). The question is whether a move is still left after the speed race. If it is, a slow bot can trade
  it on its own (autonomy requirement).
- Intraday-headline outcomes have never been pulled or looked at in this project, so the whole 2016-2026 history is
  fresh for this question.

## Rule (fixed)

**Universe each day (primary tier)**
- The same US common-stock list as `liquid_gap_orb_test.py` (`universe()`: Alpaca active and inactive assets,
  NYSE/Nasdaq/NYSE American, plain tickers, ETFs/funds excluded).
- Prior close (previous daily bar) between $10 and $500.
- Average daily dollar volume (close x volume) over the prior 20 trading days of at least $50M (prior days only).

**Event**
- An Alpaca news article (Benzinga) tagged to the symbol, **created** between 10:00:00 and 14:59:59 ET on a market
  day, classified `catalyst` by `article_type(headline, n_symbols)` in `premarket_news_test.py` (unchanged).
- Fresh: no earlier `catalyst` article for that symbol created from 16:00 ET the prior trading day up to this
  article. Only the first qualifying event per symbol per day counts.
- t0 = the one-minute bar whose minute contains the article's `created_at`.

**Reaction and direction**
- P_ref = close of the last one-minute bar that starts before t0 and no earlier than t0 - 10 minutes
  (none: no trade).
- P_react = close of the last one-minute bar that starts at or before t0 + 1 minute and at or after t0 - 10 minutes.
- r_react = P_react / P_ref - 1. Trade only if |r_react| >= 1.0%. Direction = sign(r_react): up = long,
  down = short.

**Trade**
- Entry: open of the first one-minute bar starting from t0 + 2 to t0 + 6 minutes (none: no trade). Entry is at
  least 60 seconds after the headline's minute has ended, so it uses only information known before entry.
- Exit: close of the last one-minute bar that starts at or before entry + 29 minutes and at or before 15:59
  (a 30-minute hold, cut short at the close). No stop. Every qualifying event trades; no daily cap.
- Return: long = exit / entry - 1; short = -(exit / entry - 1); minus 2 x cost.

**Costs:** 0.15% per side primary; 0.30% per side robustness. Borrow for shorts assumed free (liquid names).
**Period (decides):** 2016-01-04 to 2026-10-23.
**Statistics:** mean net return per trade; 95% CI from a bootstrap that resamples days.
**Data:** Alpaca SIP daily bars and 09:30-16:00 one-minute bars (raw prices), Alpaca news.

## Pass bar (all six required, primary tier)

- (a) at least 1,000 trades;
- (b) mean net return per trade above 0 at 0.15% per side, day-clustered 95% CI lower bound above 0;
- (c) mean net return above 0 in both halves: 2016-2020 and 2021-2026;
- (d) positive mean in at least 6 of the 11 calendar years;
- (e) mean net return still above 0 at 0.30% per side;
- (f) not carried by outliers: the mean after dropping the best 1% of trades is still above 0.

Any failure closes this idea as specified.

## Report-only (never used to decide)

- Holds of 10 and 60 minutes, and to 15:59.
- Reaction threshold 0.5% and 2%; reaction-size terciles; long vs short; hour of day; per-year means.
- Faster entry: open of the t0 + 1 bar (speed-decay check: how much of the move happens in the first minute).
- Gross signed return (drift vs reversal, no costs).
- Placebo: non-catalyst articles (roundup / reaction types) traded with the same reaction rule.
- Small-cap tier: prior close $1-$10, or $10-$500 with 20-day dollar volume $2M-$50M; cost 0.5% per side.

## Known limits

`created_at` is Benzinga's publish time; the true release (press wire, filing) can be earlier, so part of the move
may precede t0. That only makes the test harder (the move is already partly gone), never easier. Benzinga coverage
is thinner in 2016-2018 and in 2020 (see the fade test's per-year news share). A minute with no bar (thin trading)
can push entry up to 5 minutes later. Some delisted tickers are missing from Alpaca's asset list (mild
survivorship). Shares assumed borrowable at no fee.

## Result (2026-11-11, one look, rule unchanged)

`python research/analysis/scripts/intraday_news_drift_test.py evaluate --allow-incomplete` (the flag only because the
daily-bar markers were written per collection segment; `check` confirmed 0 news days and 0 minute days missing, 0
look-ahead rows, minute-bar coverage 99.9-100% every year). Output saved under
`research/analysis/outputs/intraday_news/`. 125,809 primary-tier catalyst headlines 10:00-14:59 over 2016-2026;
only **950** moved the stock 1% or more across the headline minute and the next one.

| Criterion | Result | |
|---|---|---|
| (a) >= 1,000 trades | 950 | FAIL |
| (b) mean net > 0 at 0.15%/side, CI lower bound > 0 | **-0.174%** (CI -0.370% to +0.015%) | FAIL |
| (c) mean > 0 in 2016-2020 and 2021-2026 | -0.035% / -0.261% | FAIL |
| (d) positive in >= 6 of 11 years | 4 | FAIL |
| (e) mean net > 0 at 0.30%/side | -0.474% | FAIL |
| (f) > 0 without the best 1% of trades | -0.311% | FAIL |

**VERDICT: FAIL.** A liquid stock that reacts 1% or more to a mid-session catalyst headline does drift slightly further
in the same direction over the next 30 minutes (gross +0.13%), but less than the cost of a round trip. Report-only:
every hold (10 / 60 minutes, to the close) negative after costs; 2% reactions +0.05% (CI -0.52% to +0.63%, 225
trades); longs worse (-0.31%) than shorts (-0.01%); entering one minute earlier does not help (gross +0.12%, net
-0.18%), so the delay is not what kills it; non-catalyst placebo headlines gross +0.07%, so a real catalyst adds only
about +0.06% of drift; small-cap tier gross +0.05%, net -0.95% at 0.5%/side. This closes intraday catalyst-headline
drift as specified.
