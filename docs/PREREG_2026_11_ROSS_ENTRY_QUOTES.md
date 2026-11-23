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
