# Pre-registration: Level 2 order-book pilot on premarket small-cap movers (Databento, Nasdaq book)

_Written 2026-10-23, before any order-book data was pulled (no Databento account existed yet). Committed before
the data script runs. One look at the result; no changes afterwards._

## Why this test

- "You need Level 2 and the tape" was the one point every Reddit practitioner made. Our tape test (trades and
  top-of-book quotes, `docs/DECISION_2026_10_ROSS_EDGE.md` section 8) failed. Depth of book is the piece no test has
  seen yet.
- Databento sells historical full-depth books per exchange; a new account gets $125 of credit. There is no
  consolidated depth book for US stocks, so this pilot sees **only the Nasdaq book** (XNAS.ITCH, from 2018-05-01).
  Nasdaq carries about 1/8 of all US share volume, more in Nasdaq-listed names; the pilot reports Nasdaq's share
  of each stock's volume so the blind spot can be judged.
- This is a **pilot**: a pass earns a larger pre-registered test (more venues, more mornings); a fail closes the
  Level 2 idea for premarket small-cap movers.

## Sample (fixed, chosen without looking at outcomes)

- The premarket scanner hits used by the tape test: `research/analysis/outputs/premarket_float_hits.csv`, flags
  before 09:30 ET, on or after 2018-05-01.
- Only symbols listed on Nasdaq (Alpaca asset exchange `NASDAQ`).
- Ordered newest first (from 2026-03-25 backwards). Take as many stock-mornings as `metadata.get_cost` says fit in
  **$100** of the $125 credit (the rest is a buffer). If fewer than 200 fit, stop and do not buy; report to Joel.
- Each stock-morning's data window: MBP-10 (top 10 price levels per side) from 4 minutes before the flag minute to
  the start of the minute after the flag (the entry time).

## Feature (one, fixed)

- **Depth imbalance** = (total bid size over levels 1-10 - total ask size over levels 1-10) / (total of both),
  sampled at the end of each second over the **2 minutes before entry** (the last book state at or before that
  second), then averaged. Seconds with an empty book on both sides are skipped; fewer than 60 valid seconds: the
  stock-morning is dropped.
- Entry time = start of the minute after the flag minute, so the feature uses only data known before entry.
- **Bid-heavy** = imbalance > 0. **Ask-heavy** = imbalance < 0.

## Trade and outcome

- Buy at the open of the minute after the flag minute; sell at the close of the 10th one-minute bar (10-minute
  hold), from our SIP minute bars (`ross_scanner_bars_1m`), same as earlier premarket tests.
- Cost **0.5% per side** (the project's rule for premarket small caps after measuring a 0.71% median spread).
- Statistics: day-clustered bootstrap 95% CI.

## Pass bar (all three required)

- (a) at least 200 stock-mornings with a valid feature and outcome;
- (b) bid-heavy minus ask-heavy mean 10-minute return above 0, CI lower bound above 0 (costs cancel in the difference);
- (c) bid-heavy mean net return per trade above 0 at 0.5% per side (a strategy, not only a ranking).

## Report-only (never used to decide)

- Imbalance terciles; imbalance over the last 30 seconds; ask depth (levels 1-10) divided by the prior minute's
  volume ("thin ask"); Nasdaq's share of each stock's volume in the 5-minute window (Nasdaq trades vs SIP volume);
  results by Ross pick vs other hits; 30-minute hold; per-year means; the feature's correlation with the tape-test
  features.

## Known limits

One venue's book only (fragmented market); premarket books are thin, so a few orders swing the imbalance. Sample is
small (budget-limited). Outcomes of these stock-mornings have been studied before (flag returns are known in
aggregate); the depth feature itself is new. Databento rewrites XNAS.ITCH history on 2026-10-31 (new instrument
ids before 2023-11-28); data is keyed by symbol and date, so this does not matter here.

## Result (2026-10-26, one look, rule unchanged)

`python research/analysis/scripts/l2_book_pilot_test.py evaluate`. Databento XNAS.ITCH mbp-10, 3,256 Nasdaq-listed
premarket stock-mornings (2018-05 to 2026-03), exact cost $2.87 from the free credit (Joel approved up to $10).
46 dropped for fewer than 60 valid book seconds (including empty windows); 3,210 valid over 480 days
(bid-heavy 1,724, ask-heavy 1,486). Nasdaq carried a median 16% of each stock's volume in the window.

| Criterion | Result | |
|---|---|---|
| (a) >= 200 stock-mornings | 3,210 | PASS |
| (b) bid-heavy minus ask-heavy 10-min return > 0, CI lower > 0 | +0.09% (CI -0.38% to +0.62%) | FAIL |
| (c) bid-heavy mean net > 0 at 0.5%/side | **-1.24%** (CI -1.60% to -0.86%) | FAIL |

**VERDICT: FAIL.** Nasdaq book depth imbalance in the 2 minutes before entry does not separate premarket movers
that keep running, and buying the bid-heavy ones loses about as much as every other premarket rule. Report-only:
terciles all negative after costs; last-30-second imbalance +0.25% (CI spans 0); "thin ask" slightly worse, not
better; Ross picks on the ask-heavy side did better than on the bid-heavy side (small n). This closes Level 2 depth
for premarket small-cap movers as specified. Limit: one venue's book (16% of volume), not the consolidated book.
