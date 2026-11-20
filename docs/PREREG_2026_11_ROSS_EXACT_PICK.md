# Pre-registration: Ross selection edge at his EXACT pick time (Nov 20 2026)

## Why
October found Ross's picks beat other premarket movers (+0.96% at 10 min, paired), but his pick time was
*estimated* from the first price touch, and the flag-time version was hindsight-inflated. The pick model
(AUC ~0.85) predicted his picks but its picks lost out of sample. Before building a new pick model, test
whether his selection edge exists at all when measured from the second he actually bought.

New labels: his own order log (Lightspeed "Executed or Cancelled Orders", 2017-2018 recaps, OCR'd and
tick-confirmed 86% vs 2% chance) and 2022 live-video Positions window entries (clock-timed, tick-confirmed 82%).

## Events
- Recaps: rows of `lightspeed_logs/check.csv` with `hit == True` and side BOT. First BOT per (day, symbol); T = that time.
- 2022 live: rows of `screen_fills/check_entries.csv` with timing `clock` and `hit == True`; first per (day, symbol).
- Window: 07:00 <= T < 11:00 ET.

## Peers (what else he could have bought at T)
Scanner rebuilt hindsight-free (same rules as `ross_premarket_test.py`, extended to 11:00): 15-min bars from 04:00;
at each checkpoint 07:00-11:00 a symbol is flagged the first time it is >= +10% vs prior close, $1-$20, >= 100k shares
since 04:00, prior-day close $1-$20 and volume >= 50k. Universe = cached Alpaca asset list incl. delisted.
Peers of an event = symbols flagged at a checkpoint ending <= T, excluding every symbol Ross bought that day.
Events with no peers are dropped (count reported).

## Measurement
1-min SIP bars. Entry = open of the first minute starting after T, same minute for Ross's stock and each peer.
Return at h minutes = close of the h-th bar / entry open - 1, less round-trip cost (0.5%/side before 09:30, 0.3% after).
- **Primary:** paired difference at h = 10: Ross return minus mean peer return, per event; mean with 95% bootstrap CI
  clustered by day (4,000 resamples). **PASS = CI lower bound > 0.**
- Secondary (report only): h = 5, 30; Ross absolute net return; split premarket / after open; split recap / live.

## Decision
- PASS: his selection edge is real at the moment he commits -> build the pick model (rank peers at T, top-5 recall,
  walk-forward, sealed holdout with its own prereg), and test model-B timing on his picks.
- FAIL: the October "selection edge" was estimation artefact; a pick model that copies him has nothing to copy.
  Report and stop this line.
No parameter of this test changes after results are seen.

## Results (run Nov 20 2026, `research/analysis/scripts/ross_exact_pick_test.py`) — FAIL
154 events on 83 days (139 recap 2017-18, 15 live 2022); 146 with peers (median 3 peers); only 77 of his stocks were
flagged by the >=10% scanner at all. 93% of events are after 09:30 (his 2017-18 style).

| h | Ross minus peers (paired) | Ross stock | peers |
|---|---|---|---|
| 5 min | -2.58% [-4.30, -0.78] | -3.31% | -0.92% |
| **10 min (primary)** | **-3.43% [-5.32, -1.43]** | -4.62% | -1.29% |
| 30 min | -3.58% [-6.65, -0.27] | -5.18% | -1.85% |

Same sign in every split (premarket n=8, after open, recap, live 2022 n=11). Bought the minute after Ross and held,
his stock does WORSE than the other movers.

Context (not part of the test): from the same order logs, his own avg sell / avg buy per stock-day = **+1.31% mean,
+1.48% median, 60% green** (131 stock-days), median 5.5 min from first buy to last sell. The stock he bought falls
~4.6% within 10 minutes, yet he exits ahead. In this sample his edge is execution (get in on the first move, get out
within minutes), not which stock.

Decision per prereg: the October "selection edge" does not survive exact pick times -> no pick model that copies his
choices. Effort goes to model B (entry/exit timing), with his real exits as labels.
Caveats: mostly 2017-18 recap days after the open (his premarket-heavy 2022+ style is n=8/11 here); 43 events lack
bars at some horizon; entry one minute after his buy at bar open.
