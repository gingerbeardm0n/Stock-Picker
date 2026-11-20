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
