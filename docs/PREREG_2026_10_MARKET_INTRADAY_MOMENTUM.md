# Pre-registration: market intraday momentum on SPY / QQQ (published-strategy replication)

_Written 2026-10-23, before any data for this test was pulled. Committed before the data script runs.
One look at the results; no changes afterwards._

## Why this test

- Every small-cap and single-stock rule we tested loses to trading costs. SPY and QQQ cost almost nothing to trade
  (spread about $0.01 on a $400-700 price, so about 0.002%).
- The published idea: Gao, Han, Li and Zhou (2018, Journal of Financial Economics), "Market intraday momentum".
  The S&P 500 ETF's return over the first half hour (prior close to 10:00) predicts its return over the last half
  hour (15:30 to close). Their sample was 1993-2013. Later work (for example Baltussen, Da, Lammers and Martens, 2021)
  reports the effect across many futures markets and ties it to dealers hedging options (gamma). Rules here come from
  memory of those papers' summaries; the papers were not re-read for this test.
- **Our whole sample (2016-2026) is after the original paper's sample**, so it is a true out-of-sample check.
- This is not a Ross Cameron idea. It is a jTrader research idea that a bot could run with one order a day.

## Rule (fixed)

- **Instruments:** SPY (primary) and QQQ (confirmation). Raw (unadjusted) Alpaca SIP prices.
- **Signal:** r_first = (close of the 09:59 one-minute bar) / (prior trading day's official close) - 1.
  The prior close is the daily bar's close. r_first > 0: long. r_first < 0: short. Exactly 0: no trade.
- **Entry:** the open of the 15:30 one-minute bar.
- **Exit:** that day's official close (the daily bar's close, reachable with a market-on-close order).
- **Skipped days:** days with no 09:59 or 15:30 bar (early closes, data gaps) and the first day of the sample.
- **Costs:** 0.02% per side primary (conservative for SPY/QQQ); 0.05% per side robustness.
- **Counting:** one trade per instrument per day. Results are reported as the net percent return per trade.
- **Period:** 2016-01-04 to 2026-10-22.
- **Statistics:** bootstrap 95% CI resampling days.
- **Known small bias:** raw prices mean the prior-close-to-10:00 return includes the ex-dividend drop on about four
  days a year. Decided now: leave it in (it only affects the signal, never the traded return).

## Pass bar (all six required, all on SPY unless stated)

- (a) at least 2,000 trading days with a trade;
- (b) mean net return per trade above 0 at 0.02% per side, bootstrap 95% CI lower bound above 0;
- (c) QQQ mean net return per trade above 0 at 0.02% per side;
- (d) mean net return per trade still above 0 at 0.05% per side;
- (e) positive mean in at least 6 of the 11 calendar years 2016-2026;
- (f) not carried by outliers: the mean after dropping the best 1% of days is still above 0.

Any failure closes this idea.

## Report-only (never used to decide)

- The paper's two-signal version: trade only when r_first and the 15:00-15:30 return agree in sign.
- High-volatility days: |r_first| in the top third of the trailing 250 trading days (no look-ahead).
- Exit at the close of the 15:59 one-minute bar instead of the official close.
- 2020 excluded; per-year means; long-only and short-only splits; gross (no costs).

## Known limits

Rules come from memory of published summaries. Only two instruments, so the sample is about 2,700 days each and
the effect, if any, is a few hundredths of a percent per day: the CI may be wide. Shorting SPY/QQQ is assumed free.

## Result (2026-10-23, one look, rule unchanged)

`python research/analysis/scripts/market_intraday_momentum_test.py evaluate`. 2,702 SPY days and 2,701 QQQ days,
2016-01-05 to 2026-10-22.

| Criterion | Result | |
|---|---|---|
| (a) SPY >= 2,000 trading days | 2,702 | PASS |
| (b) SPY mean net > 0 at 0.02%/side, CI lower bound > 0 | **-0.045%** (CI -0.057% to -0.034%) | FAIL |
| (c) QQQ mean net > 0 at 0.02%/side | -0.039% | FAIL |
| (d) SPY mean net > 0 at 0.05%/side | -0.105% | FAIL |
| (e) SPY positive in >= 6 of 11 years | 0 of 11 | FAIL |
| (f) SPY mean > 0 without the best 1% of days | -0.060% | FAIL |

**VERDICT: FAIL.** Report-only: with no costs at all the signal is worth nothing (SPY -0.005%, CI -0.017% to +0.006%;
QQQ +0.001%, CI -0.012% to +0.015%). The paper's two-signal version, high-volatility days, the 15:59 exit, excluding
2020, longs and shorts all show nothing either. On 2016-2026 the first half hour does not predict the last half hour
of SPY or QQQ. The effect reported for 1993-2013 is not present after it. This idea is closed.
