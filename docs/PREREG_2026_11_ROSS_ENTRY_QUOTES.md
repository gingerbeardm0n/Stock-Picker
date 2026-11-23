# Pre-registration: do quotes (bid/ask) help find the second Ross buys? (model B step 1b, DRAFT for Joel's OK)

## Question
Step 1 (docs/PREREG_2026_11_ROSS_ENTRY_TRIGGER.md) found his buy **minute** from trade prints, but not his **second**
(within 15 s: 0.55, coin flip inside the range). He watches the bid/ask and sizes. If we add those, does the model get
closer to his exact second?

## Data
- Same labels, same 130 stock-days, same dev / sealed-holdout split (holdout = 15 days from 2018-05-03), same
  2022 out-of-era set.
- Free Alpaca SIP quotes (checked: back to 2017, ~1,300-8,000 updates per 30 min), 04:00-11:30, cached.
  These are each exchange's best bid/ask + size; we rebuild the national best bid/offer (highest bid, lowest ask
  across exchanges). NOT full level 2 depth (other price levels), NOT his Time & Sales colors.
- Quote sizes in 2017 are in round lots (x100) -> sizes used as ratios, not raw.

## What the model sees (added to the strip-check print inputs)
At second s, from quotes strictly before s:
spread (cents and %); bid size, ask size, bid/(bid+ask) imbalance; ask price moves up in last 5 / 15 s (ask being
lifted); seconds since the ask last moved up; ask size now vs 5 s ago (ask being eaten); number of exchanges at the
best ask; quote update rate last 5 s vs last 5 min; share of last-15-s prints at or above the ask (buyers paying up);
mid-price change last 5 s.

## Model and leak guard
Same LightGBM settings, no tuning. Prints use the strip rule (own-price prints in the last 2 s dropped).
Quotes could also show his own fill (ask jumps after he takes it), so two versions are run:
- **A (main):** quotes before s.
- **B (leak guard):** quotes before s-2.

## Pass / fail
Scored on the sealed holdout, at the hard level that matters: his buy second vs other seconds **within 60 s** of it.
- **PRIMARY: version A minus the prints-only strip model (0.638), paired on the same 66 buys, bootstrap CI by day.
  PASS = CI lower bound > 0** (quotes add real second-level skill) **AND version B's gain is also above 0**
  (point estimate). If A passes but B shows no gain -> flagged "likely leak", not a pass.
- Also reported: within 15 / 30 s / 2 min / whole day; which quote inputs matter most; the money check
  (buy +1 s, sell half +25 s, rest +90 s, 0.2%/side vs Ross ceiling vs random); 2022 out-of-era.

## What it would and would not mean
- PASS: the bid/ask carries part of his trigger; model B should be built with quotes (and the live bot needs a
  real-time quote feed, which Tradier production gives). Does NOT mean the exact second is solved or that it makes
  money (money check + Step 2 exits).
- FAIL, possible reasons before any conclusion: (a) his trigger sits in depth/L2 (size stacking, hidden buyers) that
  top-of-book does not show, (b) his reaction itself varies by 1-3 s so the "exact second" is noisy (score within
  +-2 s, exploratory), (c) 66 holdout buys too few (212 new videos later), (d) 2017 quote data quality.
  One test does not end the idea.
- Limits: 2017-18, mostly after the open; no L2; 66 holdout buys -> wide CI.

## Cost / time
Free data, no DB, no paid feed. ~158 stock-days of quotes, ~1 h download + run.
No parameter changes after results are seen; extra cuts labelled exploratory.

## Results (run Nov 23 2026, `research/analysis/scripts/ross_entry_quotes_test.py`) — PASS by the written rule, weak
Deviation: Alpaca SIP quotes are already national best bid/offer, so no rebuild; "exchanges at best ask" dropped.
Quote coverage 100% of rows.

Sealed holdout rank skill, his buy second vs "no" seconds within w:

| w | prints only (strip) | A: + quotes before s | B: + quotes before s-2 |
|---|---|---|---|
| 15 s | 0.567 | 0.625 [0.53, 0.70] | 0.583 |
| 30 s | 0.610 | 0.677 | 0.623 |
| **60 s** | **0.644** | **0.713** [0.64, 0.77] | **0.660** |
| 2 min | 0.678 | 0.745 | 0.691 |
| all day | 0.876 | 0.897 | 0.882 |

Primary (within 60 s, paired): A gain **+0.069 [+0.021, +0.101]**; B gain +0.016 [-0.031, +0.051].
A CI low > 0 and B point > 0 -> PASS per rule. But B's gain is small and its CI spans 0: most of what quotes add
sits in the last 2 s, the same window as the print signal.
Version A leans on: mid-price change last 5 s 26%, seconds since the ask last moved up 14% (quote inputs 47% total).
2022 out-of-era within 60 s: prints 0.525 -> with quotes 0.557 (both near coin flip).
Money check (A fires, +1 s / half +25 s / rest +90 s): mean +0.23%, median -0.72%, 43% green, CI [-1.09, +1.17]
-> nothing; Ross's own seconds with the same exit +0.55%; random -0.16%.

Possible explanations:
- Real: he buys right as the ask starts lifting / mid ticks up (fast reaction, ~1-2 s) -> learnable, needs sub-second feed.
- Leak: his own buy lifts the ask; with time-stamps confirmed only within [t-2, t+1] some of that is in "before s".
- Both, as with prints. Version B (no last-2-s quotes) barely helps -> cannot separate with this data.
What holds either way: quotes older than 2 s add little; the minute is findable, the second is not yet; fixed exits
make no money even on his own entries -> exits (Step 2) matter.
