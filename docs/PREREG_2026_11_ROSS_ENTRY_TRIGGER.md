# Pre-registration: can the tape tell us the second Ross buys? (model B step 1, DRAFT for Joel's OK)

## Question
On a stock Ross is trading that day, using only what the tape showed BEFORE a given second, can a model tell which
seconds he starts a trade, better than chance and better than a simple "new high + volume burst" rule?
And if a bot fired at the model's seconds (1 s late), would it make money like copying him does?

## Why
Step 0 (docs/PREREG_2026_11_ROSS_COPY_LATENCY.md) showed his timing is worth ~+2% per trade if copied within 1 s, and
almost nothing by 5 s. A bot only gets that if it can spot those seconds itself. This test asks whether the tape holds
the signal.

## Data
- Labels: first buy of each episode in his 2017-18 order log (tick-confirmed), same 241 episodes as Step 0.
- Out-of-era check: 2022 live-video entries (clock-timed + tick-fit, tick-confirmed), report only.
- Free Alpaca SIP prints (cached 04:00-11:30 ET) + daily bars for prior close. No paid data, no DB.
- No quotes / order book in v1 (noted limit; he watches L2).

## Examples the model learns from
- **Yes** = the second of his first buy in each episode.
- **No** = every other second on the same stock that day, 07:00-11:30, that has at least one print (a bot can only
  buy when something trades), excluding seconds within 3 s of any of his buys (too close to call).
- Only stocks he traded that day. Picking the stock is model A's job, not this one.

## What the model sees at second t (only prints strictly before t)
Price vs high of day so far; seconds since last new high; % up from prior close; distance to next whole / half dollar;
price change last 5 / 15 / 60 s; trade count and volume last 5 / 15 / 60 s vs last 5 min; share of upticks last 15 s;
average print size; distance from VWAP; time of day.

## Model
LightGBM with fixed small settings (depth 3, 200 trees, learning rate 0.05, class weight balanced). No tuning
(nothing to overfit with). Baseline rule: "price at a new high of day AND last-15 s volume >= 3x the 5-min rate".

## How it is scored (no peeking)
- Days sorted by date. **Last 20% of days (about 15) = sealed holdout**, untouched until the final run.
- Earlier days: 5-fold cross-validation grouped by day (a day never in train and test at once), to check it works
  before touching the holdout. Settings above do not change after seeing these.
- Score = **"rank skill"**: inside each stock-day, chance that a random Ross-buy second gets a higher model score than a
  random other second. 0.5 = coin flip, 1.0 = perfect. 95% CI by bootstrap clustered by day.

## Pass / fail
- **PRIMARY: on the sealed holdout, rank skill CI lower bound > 0.5 AND point estimate above the baseline rule's.**
- Money check (report, not pass/fail): on holdout days, model fires at its top seconds (threshold set on training days
  so it fires about as often per stock-day as Ross did; one fire per 60 s max). Each fire: buy at first print 1 s later,
  sell half at +25 s and rest at +90 s (his median first and full exits), 0.2%/side. Compared with Ross's own buy
  seconds under the same exit (ceiling) and random print-seconds on the same stock-days (chance).
- Also reported: which inputs the model leans on most (to read back what "his trigger" looks like), and the 2022
  out-of-era rank skill.

## What it would and would not mean
- PASS: the tape before his buy looks different in a way a small model can see -> his entry trigger is learnable;
  next is Step 2 (first partial exit) and adding quotes/L2. Does NOT prove a live bot makes money (fills, speed, and
  the stock-picking step are separate).
- PASS rank but money check flat: model finds "busy breakout" seconds but not his better ones -> need finer inputs
  (quotes, L2, round-number tape reading) or more labels (212 new videos).
- FAIL, possible reasons to check before concluding anything: (a) the signal lives in quotes / L2 / news that prints
  alone don't show, (b) 241 examples too few (wait for 2022+ labels), (c) "first buy of an episode" mixes different
  setups (split by setup later), (d) his exact second partly depends on his own reaction delay (score within +-2 s too,
  exploratory). One test does not end the idea.
- Limits: 2017-18 only, mostly after the open; ~240 yes-examples; small holdout (~50 buys) -> wide CI.

No parameter changes after results are seen; extra cuts are labelled exploratory.

## Results (run Nov 20 2026, `research/analysis/scripts/ross_entry_trigger_test.py`) — PASS (primary), with big caveat
Note: LightGBM native API used (sklearn wrapper not installed); same settings, "balanced" = positives weighted n_no/n_yes.
130 stock-days 2017-18, 241 yes / 382,514 no seconds. Dev 57 days (175 yes), holdout 15 days from 2018-05-03 (66 yes).

| | model rank skill | baseline rule |
|---|---|---|
| dev (cross-validated) | 0.928 [0.914, 0.942] | 0.535 |
| **sealed holdout (primary)** | **0.885 [0.842, 0.928]** | 0.510 |
| 2022 live, out of era (93 buys) | 0.625 [0.404, 0.763] | 0.504 |

Inputs it leans on: 60-s price change 23%, 5-s change 13%, distance from VWAP 13%, time of day 12%, 5-s volume 10%.

Money check (holdout; buy +1 s, sell half +25 s, rest +90 s, 0.2%/side):
model fires n=67 mean +1.29% / median -1.00% / 46% green, CI [-0.30, +3.18]; Ross's own buy seconds with the same
fixed exit n=59 mean +0.55% / median -0.02%, CI [-0.56, +1.97]; random seconds n=1,259 mean -0.18%.

### Exploratory (not pre-registered, `ross_entry_trigger_explore.py`)
Holdout rank skill when "no" seconds are only those near his buy:
within 10 min 0.80 · 5 min 0.78 · 2 min 0.74 · 60 s 0.69 [0.62, 0.76] · 30 s 0.64 [0.57, 0.71] · 15 s 0.58 [0.50, 0.66].
Mean model score climbs into his buy: t-30 s 0.44, t-5 s 0.49, t-4 s 0.53, his second 0.60 (quiet seconds median 0.01).

### What it means (and doesn't)
- The model clearly finds **the minute** he gets in (stock running in the last 60 s, near/above VWAP, his hours) far
  better than the rule. Pinning **the exact second** is much weaker: 0.58 vs seconds within 15 s, CI touching 0.5.
  Step 0 says the money lives in a 1-2 s window, so second-level precision is what is missing.
- Most of the 0.885 comes from telling "his kind of moment" from quiet seconds, which is real but easier.
- Money check is inconclusive: the fixed 25 s / 90 s exit turns even HIS entries into ~+0.5% (vs +2.2% with his real
  exits at 1 s late) -> his exits carry much of the edge; model fires +1.3% mean but median -1.0%, CI spans 0.
- 2022 out-of-era is weak and uncertain (different, premarket-heavy style; 23% of those times are tick-fitted).
- Possible leak to check: his first-buy times are tick-confirmed within [t-2 s, t+1 s], so for some buys his own print
  may sit just before t and feed the 5-s inputs; the score jump t-4 s -> t (0.53 -> 0.60) could partly be that.
  Fix to test: build inputs from prints before t-2 s.
- Not tested: quotes / L2 (he reads them), second-level setups, more labels (212 videos pending).

### Leak check (Nov 20, `--lag 2`: inputs only from prints before t-2 s; same model, same split)
| | lag 0 (above) | lag 2 |
|---|---|---|
| sealed holdout, all seconds that day | 0.885 | 0.872 [0.819, 0.916] (still PASS) |
| "no" within 2 min | 0.74 | 0.63 [0.56, 0.70] |
| "no" within 60 s | 0.69 | 0.58 [0.50, 0.65] |
| "no" within 15 s | 0.58 | **0.50 [0.41, 0.58] = coin flip** |
| money check, model fires | +1.29% mean | +0.16% mean, median -1.21%, 38% green |
| 5-s price change share of model | 13% | 3% |

Reading: the second-level skill at lag 0 came mostly from the last 2 s before his buy. Two explanations, not
separable with this data: (a) his own print leaking in (tick-confirm window t-2), (b) he really reacts to prints in the
last 1-2 s, which a 2-s gap also hides. Either way, from prints >= 2 s old the model finds his stretch of minutes, not
his second. Next checks: remove his own print by price + size match and rerun at lag 0 (separates a from b); add
quotes (bid/ask, sizes) which he watches.

### Own-print strip check — design (written before running, Nov 23; Joel OK'd)
Question: is the last-2-s signal his own print (leak) or a real fast reaction to the tape?
Rule, applied the same way to EVERY second s (yes and no, no Ross knowledge): build inputs from prints before s, but
drop prints in [s-2, s) whose price is within $0.01 of the first print at/after s (the price a buyer at s pays —
where his own fill would sit). Prints at other prices in those 2 s are kept. Same model, settings, split, scoring.
Also reported: at his buy seconds vs no-seconds, how often anything was dropped and how many shares.
- Skill near his buy (within 15 / 60 s) comes back toward lag-0 levels -> real reaction to other prices in the last
  2 s; learnable (bot needs sub-second speed).
- Stays ~0.5 like lag 2 -> the signal was prints at his price in the last 2 s: his own print, OR others printing at
  his price right before him (this check cannot tell those two apart; size matching would be next).

### Own-print strip check — results (Nov 23, `--strip`)
Prints dropped (same rule everywhere): at his buy seconds something dropped 92% of the time, median 2,592 shares
(his median fill ~2,000); at other seconds 67%, median 1,250 shares -> his own print very likely sat in that window.

| holdout score | lag 0 | strip own-price prints | lag 2 (hide all) |
|---|---|---|---|
| all seconds that day | 0.885 | 0.876 | 0.872 |
| within 2 min | 0.74 | 0.68 | 0.63 |
| within 60 s | 0.69 | 0.64 [0.56, 0.71] | 0.58 |
| within 30 s | 0.64 | 0.60 [0.52, 0.67] | 0.54 |
| within 15 s | 0.58 | 0.55 [0.47, 0.64] | 0.50 |
| money check, model fires (mean / median) | +1.29% / -1.00% | +0.75% / -0.75% | +0.16% / -1.21% |

Reading: the result lands in between, not at either pre-written outcome. About half the near-buy skill lost at lag 2
comes back when only his-price prints are removed -> other prints in the last 2 s carry real signal (a fast-reaction
component is real). The other half was prints at his price in the last 2 s (his own fill, or others trading at his
price just before him; not separable here). Exact-second pinpointing from prints stays weak (15 s: 0.55, CI spans 0.5);
money check still inconclusive. Next: add quotes (bid/ask + sizes), which he watches.
