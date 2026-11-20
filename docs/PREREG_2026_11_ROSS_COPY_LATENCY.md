# Pre-registration: does a perfect copy of Ross's timing make money, and how late can it be? (Nov 20 2026)

Step 0 of model B (entry/exit timing). Plain-English card agreed with Joel before running.

## Question
If a bot bought the exact second Ross bought and sold the exact seconds he sold, at real market prints, would it
make money after costs? And how fast does that disappear as the bot is late by 1, 2, 5, 10, 30 seconds?

## Why first
If a perfect copy of his timing loses money, no model trained to imitate his timing can make money (model B would
need a different target). If it pays, the delay curve sets the bot's speed budget.

## Data
- Ross's 2017-18 Lightspeed "Executed or Cancelled Orders" log, OCR'd: `lightspeed_logs/check.csv`.
  Only fills tick-confirmed (`hit == True`, 86% of rows) are used, so times are trustworthy to the second.
- Free Alpaca SIP trade prints (cached, 04:00-11:30 ET).
- 2022 live-video exits are not extracted yet; not in this test.

## Trades
Per (day, symbol), fills in time order. An episode = a run of buys followed by a run of sells
(the same grouping used for the hold-time numbers). Shares = his filled quantity. Episodes need >= 1 buy and >= 1 sell.

## What the copy does
For delay D in {0, 1, 2, 5, 10, 30} seconds:
- Each of his fills at second t is copied with the same share count at the price of the first SIP print at or after
  t + D. (His log shows whole seconds; his fill happened in [t, t+1).) No print within 60 s -> episode dropped at
  that delay (count reported).
- Episode return = share-weighted avg copy sell price / share-weighted avg copy buy price - 1 - 0.4%
  (0.2% per side for spread + slippage).
- Reference (not a copy): the same formula using his own logged prices, no cost.

## What I report
For each delay: n episodes, mean and median net return, % green, mean with 95% bootstrap CI clustered by day
(4,000 resamples). Also split by how long he held (fully out <= 60 s vs longer).

## Pass / fail
- **Primary: delay 0. PASS = CI lower bound of the mean > 0** (a perfect copy makes money after costs).
- Delay curve: the speed budget = largest delay whose mean CI lower bound is still > 0. Reported, not pass/fail.

## What it would and would not mean
- PASS: copying his timing pays; model B's labels (his buy/sell seconds) are worth learning; delay curve tells how
  fast the bot must react. Does NOT show a model can learn his timing (that is Step 1).
- FAIL, possible reasons to check before any conclusion: (a) his profit comes from fills a copier cannot get
  (bid/ask placement, pre-print fills), (b) 0.2%/side is too harsh or too soft (re-report at 0.1% and with no cost),
  (c) OCR share counts skew the weighting (re-report unweighted). One test does not end the idea.
- Limits: 2017-18 only, mostly after the open; some fills missed by OCR; sells after 11:30 not in tick cache.

No parameter changes after results are seen; extra cuts are labelled exploratory.
