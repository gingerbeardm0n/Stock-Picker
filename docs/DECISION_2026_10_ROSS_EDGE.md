# Decision: what to do with jTrader after the Ross Cameron tests

_Written 2026-10-18. Supersedes the Gate 1 plan in `docs/DEEP_REVIEW_2026_09.md` §4, which was
about re-optimizing the retired strategies. Owner: Joel. Status: **tape test run 2026-10-19: FAIL** (see section 8). Joel approved: run the tape test and switch off the live session. He did NOT agree to stop jTrader or make jSwing the main project (correction 2026-10-20)._

## TL;DR

1. On 1-minute data, **no mechanical rule we could build beats realistic trading costs** on the
   stocks Ross Cameron trades. We ran 14 tests over Oct 2–18.
2. The **only real signal is Ross's own premarket stock picks**: on the same morning, his stock beat
   the other premarket movers by about +1.0% (10 min) to +1.8% (30 min). That is roughly the size
   of the measured cost of trading these stocks (about 1.1% round trip at the median), and it
   depends on knowing which stock he picked.
3. The remaining explanation is the one Reddit gave us unanimously: **his edge lives in the tape
   and Level 2 in the seconds before he clicks** (plus his audience piling in), which 1-minute
   bars cannot see.
4. **Recommendation: one last, time-boxed test of that idea using free historical tape data,
   with the pass rule below committed in advance. Decide by 2026-11-01.** Pass: a small Level 2
   and latency pilot. Fail: pause jTrader and make jSwing the main project.
5. Regardless of the choice: switch off the dead daily live session, merge this research branch,
   and post the drafted Reddit replies.

## 1. What we tested

All tests use honest fills, hindsight-free scanners, and out-of-sample or paired-by-day
comparisons. Scripts are in `research/analysis/scripts/`. Detail is in the memory note
`ross_oracle_test_rough.md`.

| # | Test | Result | Verdict |
|---|------|--------|---------|
| 1 | Honest simulator (Sep) | Sealed scalp result PF 3.31 → 0.58 once stops can gap | Old strategies were never real |
| 2 | Do our scalp entries predict moves? | −0.8% one bar later, all confidence ranges below zero | No |
| 3 | Do we even have his stocks? | Only 41% in our DB (survivorship); backfill → 82% | Fixed |
| 4 | His own entries, a bot one minute late | Average slightly positive, typical trade loses | No reliable timing edge |
| 5 | His picks vs other gappers after 9:30 | −0.06% paired | No edge after the open |
| 6 | **His picks vs other flagged movers, premarket** | **+0.96% (10 min) / +1.76% (30 min) paired, range above zero** | **The one real signal** |
| 7 | Can a model learn his picks? | Predicts which he picks (AUC 0.79–0.88), but its picks lose: −0.5% / −1.8% | Learns his style, not his edge |
| 8 | Buy the premarket breakout | −1.7% / −2.4% | No |
| 9 | News catalyst vs no news | Catalyst movers beat no-news movers by ~1%, but are ~flat in absolute terms | A filter, not a strategy |
| 10 | AI rating of the headlines | Ratings don't sort winners; it rated his picks *lower* | No |
| 11 | Low float | ≈0 difference | No |
| 12 | Hot vs cold small-cap market | His picks ≈ flat in cold markets, positive in warm ones; buying every flag loses in all | Regime matters for him, not for rules |
| 13 | Wait for the pullback, buy the first new high | −0.69% / −1.03%; −0.41R with a stop under the pullback | No |
| 14 | Real premarket spreads | Median 0.71%; cost of crossing ≈ 0.35% median, 0.53% mean per side; 34% wider than 1% | Our 0.3%/side was optimistic |

## 2. What it means

- Ross's **measurable** edge is picking the right premarket mover on a news day in a warm market.
  It is about +1% per trade from his pick time, which a bot without his judgment can't reproduce
  and which roughly equals the cost wall.
- What our data **cannot** see: the tape and Level 2, ten-second execution, his audience, and how
  he exits (scaling out into strength with limit orders, which earns some of the spread back).
- Known biases in our evidence: his trades are the ones he chose to talk about in recaps (a third
  are losers, so not only highlights); his entry times are estimated; flag-time measures of his
  picks are inflated by hindsight. None of these would turn the mechanical results positive.
- Community (r/Daytrading, Oct 15–18: 13 comments on our post plus a 46-comment thread from another
  builder): "you need Level 2 and the tape" was unanimous. One person who did automate order flow
  found an edge only at timescales that need high-frequency queue modelling, which he couldn't win.

## 3. Options

| Option | What it does | Cost | Time | Notes |
|---|---|---|---|---|
| **A. Tape test** | Tests whether order flow at the flag (tape speed, buying at the ask, big prints, spread, quote sizes) separates the movers that keep running | $0: Alpaca historical quotes are confirmed free; trades endpoint to confirm first | 1–2 days | Low odds. Even a pass faces the speed problem live |
| B. Level 2 pilot | Order-book depth from Databento (Nasdaq TotalView) on a few hundred stock-mornings | $0–125 free credit, then about $199/month to continue | ~1 week | Only after A passes. Small caps trade on many venues, so one book is a partial view |
| C. Live real-time data | Any live intraday jTrader needs it (Tradier is dead) | Alpaca SIP $99/month, or Schwab API free (includes Level 2, needs a weekly re-login) | days | Only matters if A and B pass |
| D. Pause jTrader | Switch off the daily session, archive findings, keep the DB | $0 | 1 hour | The session has placed **0 trades since Jul 20** and runs retired configs |
| E. Focus on jSwing | Daily bars, liquid stocks, multi-day moves where a 0.5% cost is small | — | ongoing | Has a promising config but tiny samples (13–20 positions per window). Its own risks |
| F. Futures / tape reading | One order book, cheap Level 2: the venue the community suggested for tape strategies | data plus new broker | weeks+ | A new project, not a Ross replication |

Not on the list: alerts where Joel clicks (fails the autonomy requirement), and funding Tradier
(a data feed doesn't fix a strategy without an edge; Alpaca or Schwab are cheaper anyway).

## 4. Recommendation

**Do A now, time-boxed, with the rule in §5 frozen by this commit. Do D now regardless. Put spare
time into E.** Rationale: the tape is the only remaining hypothesis our free data can test, it
reuses everything already built (scanner, bars, quotes, honest exits), and it gives a clean answer
either way. Stopping today is also defensible. Sunk cost is not a reason to continue, and the odds
of a pass are low.

```
Tape test (decide by 2026-11-01)
├─ PASS → Level 2 pilot on Databento credit + live latency check on Alpaca paper (2 weeks)
│         ├─ both hold → paper bot at 0.5%/side costs, then the deep review's Gate 2
│         │              (tiny real money, kill checks at 40 and 100 trades)
│         └─ either fails → pause jTrader
└─ FAIL → pause jTrader (archive, keep data); jSwing becomes the main project
Hard stop for jTrader stays 2027-03-31.
```

## 5. Pre-registered rule for the tape test (frozen before any tape data is pulled)

- **Population:** the hindsight-free premarket scanner hits (`outputs/premarket/scanner_hits.pkl`,
  6,046 stock-mornings).
- **Decision time:** the scanner flag. Features use only Alpaca SIP trades and quotes from the
  5 minutes before the flag. Exactly these five:
  1. tape speed: trades in the last 2 minutes ÷ trades in the 3 minutes before that;
  2. buy pressure: share of volume printed at or above the ask in the last 2 minutes (quote rule);
  3. big prints: share of volume in prints ≥ 10,000 shares in the last 5 minutes;
  4. quoted spread at the flag;
  5. bid size ÷ (bid size + ask size) at the flag.
- **Model:** logistic regression (as in `ross_pick_model_test.py`), walk-forward by year: train on
  all years before the test year, predict "30-minute net return > 0".
- **Trade:** each morning, only the top-scored hit; buy at the next minute's open; exit after 30
  minutes; **0.5% cost per side**.
- **PASS requires all four:** (a) ≥ 300 out-of-sample trades; (b) mean net return > 0 with a
  day-clustered 95% CI lower bound > 0; (c) mean positive in at least 2 of the 3 most recent test
  years; (d) beats the same model without the tape features by ≥ 0.5% per trade.
- One look. No feature, threshold, cost or hold changes after seeing results. Report-only
  sensitivity: 10-minute hold, 1.0% per side.
- **Any failure ends the Ross-replication line.**

### 5a. Addendum (2026-10-19, written BEFORE any tape feature was computed)

Only an access probe has been run: 5 random flagged stock-mornings, trade counts only. It confirmed
Alpaca SIP historical trades are free on our key, fast (0.1-0.5 s per call), and show 5 to 2,339
trades in the 5 minutes before a flag, from 6 to 11 exchanges, with about 40-60% of trades odd lots
(under 100 shares). Data handling, frozen now:

- **Trades kept:** only those whose condition codes are all within {' ', '@', 'T', 'F', 'I', 'E'}
  (regular, extended-hours, intermarket sweep, odd lot, automatic execution). Everything else
  (out-of-sequence, bunched, average-price, contingent, cash, next-day, etc.) is dropped.
- **Odd lots** stay in trade counts and volume totals (they are real trades); the "big print"
  feature is unaffected (it needs >= 10,000 shares).
- **Buy/sell classification:** quote rule against the last quote at or before the trade timestamp
  (price >= ask is a buy, <= bid is a sell). Anything in between uses the tick rule against the
  previous kept trade. Trades with no quote in the preceding 60 seconds are left out of the
  buy-pressure feature only.
- **Liquidity floor:** a stock-morning with fewer than 20 kept trades in the 5 minutes before the
  flag cannot be traded and is excluded from scoring; the count is reported.
- **No imputation:** stock-mornings with any missing feature are excluded and counted.
- **Minimum training set:** a test year is scored only if at least 400 earlier stock-mornings
  with complete features exist.
- Everything else in section 5 stands unchanged.

### 5b. Addendum (2026-10-19, still before any tape feature was computed)

Details that section 5 left open, fixed now. The implementation is `research/analysis/scripts/tape_feature_test.py`,
committed together with this note.

- **Features as model inputs:** log(tape speed ratio), buy share, big-print share, log(relative spread),
  bid-size share, standardized on the training years. Tape speed ratio = (trades in the last 2 minutes + 1)
  divided by (trades in the 3 minutes before that + 1). Buy share = buy volume / (buy + sell volume) over classified
  trades in the last 2 minutes.
- **Classifier:** logistic regression, C = 0.3, balanced class weights (same as `ross_pick_model_test.py`).
- **Label and outcome:** net 30-minute return after 0.5% per side > 0. Entry = open of the first 1-minute bar at or after
  the flag; exit = close of the last bar within 29 minutes of that bar's start.
- **Selection:** highest predicted probability per morning among stock-mornings that pass the liquidity floor and have
  all five features.
- **Criterion (d) comparator:** the same one-trade-per-morning rule with no tape information, i.e. the average net
  return of all qualified hits that morning (the exact expectation of a random pick). The bar-feature pick model is
  reported for context only and does not enter the verdict.
- **"3 most recent test years"** = the three latest years that were scored.
- **Confidence interval:** day-clustered bootstrap, 3,000 resamples.

### Note on costs in the earlier tests (correction, 2026-10-19)

Tests 2, 4-7 and 9-12 in the table above charged the 0.3% slippage on the **exit only**, so their *absolute* returns are
about 0.3% too generous. Paired comparisons (tests 6, 9, 12) are unaffected. Tests 8 and 13 charged both sides. This
makes the absolute results look slightly better than they should; it does not change any conclusion.

## 6. Housekeeping (whatever is chosen)

1. Switch off the daily live session on Render (retired configs, no data feed). Needs Joel's OK;
   deploy only on a weekend or after 12:00 ET on a trading day.
2. Merge branch `claude/elated-euclid-5e0d46` to main (all October research scripts, `community/`).
3. Refresh `STATUS.md` (still dated Sep 18) and run the historian.
4. Post the drafted Reddit replies (`community/reply_drafts_2026-10-16.md` and `-10-18.md`).
5. Any future premarket simulation: cost 0.5%/side premarket, 0.3%/side from 09:45.

## 7. Decisions needed from Joel

1. Run the tape test as the last jTrader experiment under §5, or stop now?
2. OK to switch off the daily live session?
3. If the tape test fails, does jSwing become the main project?

## 8. Result of the tape test (2026-10-19, one look, rule unchanged)

`python research/analysis/scripts/tape_feature_test.py evaluate`. 5,301 stock-mornings collected;
728 below the liquidity floor, 36 missing a feature or outcome, 4,537 qualified over 519 days;
no truncated pulls. Scored years 2023-2026.

| Criterion | Result | |
|---|---|---|
| (a) >= 300 out-of-sample trades | 377 | PASS |
| (b) mean net > 0, CI lower bound > 0 | **-2.65%** (CI -3.88% to -1.31%) | FAIL |
| (c) positive in >= 2 of 2024-2026 | 0 of 3 (-2.45%, -3.48%, -2.55%) | FAIL |
| (d) beats a random pick by >= 0.5% | -1.41% (random pick -1.24%) | FAIL |

**VERDICT: FAIL.** The tape-ranked pick did *worse* than a random flagged stock in every year.
Report-only: 10-minute hold -1.52% (random -1.11%); 1.0%/side -3.78%; the bar-feature model -0.97%
(CI -2.12% to +0.28%, random -1.24%). Top picks were Ross picks 11.4% of the time vs 9.1% base rate.

Per section 4, the Ross-replication line ends here: pause jTrader as a live strategy and keep all data
and tooling. (Correction 2026-10-20: Joel is continuing jTrader as a research project; jSwing is not replacing it.) Any further jTrader idea needs its own pre-registered
test written before its data is examined. (Post-hoc note, NOT actionable: the tape ranking selecting
worse-than-random stocks suggests frenzied tape marks exhaustion; that is a new hypothesis on the same
data and could only be tested on fresh data.)
