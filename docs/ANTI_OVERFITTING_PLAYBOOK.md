# Anti-Overfitting Playbook

*Created: 2026-06-06. The methods quant/ML traders use to stop a backtest "winner" from
collapsing on unseen data — mapped to THIS project's recurring failure.*

---

## 1. The problem, stated plainly

We keep finding a config that looks great on the days the optimizer trained on, then watch it
fail on every other day. This is **overfitting**: the optimizer mines noise in the specific days
it sampled, not a real edge.

### Our own evidence (the same movie, every run)

| Run | Best on training | What happened out-of-sample |
|---|---|---|
| robust (Jan 2026) | +$1,490 | Dec 2025 validation avg **−$257** |
| pillar23_v2 | +$4,673 | universe built with **whole-day look-ahead** — cannot exist live |
| opt_5yr_v7 | +$1,089 (trial 206) | validate4: median +110, mean **~0** |
| opt_5yr_v8b | +$497 (trial 180) | validate1: median **−1,593**, mean **−2,134**, only **14%** of samples positive |

The consistency objective (variance penalty `k=1.0`) did **not** fix it. It only flattened
variance *on the days each trial sampled* — the optimizer just found a different overfit.

### Two DISTINCT problems we keep blending

- **Problem 1 — Overfitting / no holdout.** All 2021–2025 days are in-sample. The "best trial"
  is whichever config best fit *that trial's random 259-day sample*. There is no unseen data to
  catch the lie. **This doc is about Problem 1.**
- **Problem 2 — Discovery bias.** Sim picks its universe with whole-day look-ahead; the live
  scanner can only see what surged so far. Sim is inflated vs live. Fixed by the intraday
  momentum scanner plan (`concurrent-roaming-kahan.md`). Orthogonal to Problem 1.

### The root cause nobody named: 126 tunable parameters

`locked_params_v8_trial180.json` exposes **126** degrees of freedom. With zero holdout, 126 knobs
+ thousands of trials = overfitting is **mathematically guaranteed**. Standard quant practice:
tune **<15** parameters, lock the rest. The single highest-leverage fix is cutting degrees of
freedom — no objective tweak survives 126 knobs.

---

## 2. The methods (the playbook)

Ordered by how directly each attacks our failure.

### 2.1 Train / Validate / Test holdout — **do this**
Three **disjoint** date ranges:
- **Train** — optimizer tunes parameters here.
- **Validate** — optimizer *selects* the best config here. It never trains on these days.
- **Test** — sealed. Scored **exactly once**, at the very end, never tuned against. If you peek
  and re-tune, it is no longer a test.

A result that survives a true test is the only number worth trusting live.

### 2.2 Walk-forward (anchored) — **do this**
Train on window → trade the *next* unseen window → roll forward → repeat. Concatenate the
out-of-sample windows into one equity curve. This mimics real deployment: you only ever trade on
days after the ones you fit. Anchored = training start fixed, end expands.

For us: train 2021–2023 → select on 2024 → seal 2025 as the final test.

### 2.3 Purged K-fold CV + embargo (López de Prado)
Time-series samples overlap (a trade's label spans multiple bars), so naive k-fold leaks future
into train. **Purge**: drop train samples whose label window overlaps the test fold. **Embargo**:
add a gap after each test fold so post-test days don't leak back. Use when we want CV instead of a
single split.

### 2.4 Combinatorial Purged CV (CPCV)
Many purged train/test splits → a **distribution** of out-of-sample Sharpe, not one number. Feeds
the next item.

### 2.5 PBO — Probability of Backtest Overfitting
From the CPCV distribution: how often does the config that ranked #1 in-sample land below median
out-of-sample? High PBO = your selection process is overfitting. A direct score for "are we
fooling ourselves."

### 2.6 Deflated Sharpe Ratio
Discount the best Sharpe by **how many configs you tried**. We've run thousands of trials, so the
naive best is hugely inflated. Deflated Sharpe asks: is this better than the best you'd expect
from pure luck given N attempts? Usually the honest answer shrinks dramatically.

### 2.7 Plateau selection, not peak — **do this**
Pick the config sitting in a **broad robust neighborhood** of good results, not the single tallest
spike. A lone spike surrounded by bad configs is overfit by definition (tiny param change → it
dies). A plateau means the edge is insensitive to exact param values = more likely real.

### 2.8 Monte Carlo / bootstrap the trade sequence
Resample the trade list (with replacement, or reshuffle order) → P&L **distribution** + drawdown
distribution instead of a point estimate. **Our `--no-median-prune` validate runs already do a
version of this** (100 random day-samples of a fixed config). Keep them — they are our robustness
gate. The numbers in the table above came from exactly this.

### 2.9 Cut degrees of freedom — **do this first**
Fewest tunable parameters that still express the strategy. Lock the rest at sane defaults. 126 → ~12.

### 2.10 Regime awareness
Make sure train and test each span bull / chop / crash. Our stratified sampler (1 day/week × 259
weeks) already forces regime coverage within a sample — keep it. The walk-forward split must also
not put all of one regime in train and another in test.

---

## 3. What we already do right (keep)

- **Validate runs** (`--no-median-prune`, NopPruner, 100 random day-samples) = method 2.8. Our
  honesty check. This is how we caught trial 180.
- **Stratified sampler** (1 day/week × 259 weeks) = method 2.10 within a sample.
- **Consistency objective** (penalize daily-P&L std) is reasonable — but it is NOT an
  anti-overfit tool. It shapes *which* config wins on the training days; it does nothing about the
  lack of a holdout. Don't expect it to fix Problem 1.

## 4. What we're missing (the gap)

- **No holdout** (2.1) — biggest gap.
- **No walk-forward** (2.2) — `optuna_run.py` has no separate train vs score date range.
- **Selecting the peak, not the plateau** (2.7).
- **126 params** (2.9) — overfit guaranteed.
- No deflated-Sharpe / PBO accounting for the thousands of trials run (2.6, 2.5).

---

## 5. The plan (execution order)

1. **Cut params 126 → ~12.** Keep tunable: `stop_buffer`, `RR ratio`, `T1 ratio`, `T1 qty`,
   `trail stop`, `min_premarket_gain`, `min_relative_volume`, `time_decay_hour`, `min_price`,
   `max_price`, + 1–2 pattern toggles. Lock the rest at trial-180 / known-good values.
2. **Walk-forward holdout.** Add `--train-start/--train-end` and `--score-start/--score-end` to
   `optuna_run.py`. Optimizer fits on train days, the **objective is computed on score days only**.
   - Train 2021-01-01 → 2023-12-31
   - Select 2024-01-01 → 2024-12-31 (scored here; never trained)
   - **Seal 2025** — final single-shot test after selection is locked.
3. **Plateau-select** from the 2024 results: pick a config in a robust neighborhood, not the lone
   peak.
4. **Single-shot test on sealed 2025.** Report that number. That's the one we'd trust live.
5. **Then** Problem 2: intraday momentum scanner (`concurrent-roaming-kahan.md`) so sim==live
   discovery.

### Definition of done
A 2025 test (never trained, never selected against, scored once) with **positive median across
the validate-run distribution** — not just a positive point estimate. If median is positive and
the left tail is bounded, we have something real.

---

## 6. References
- M. López de Prado, *Advances in Financial Machine Learning* (2018) — purged K-fold, embargo,
  CPCV, PBO, deflated Sharpe (ch. 7, 11–12).
- Bailey & López de Prado, "The Deflated Sharpe Ratio" (2014).
- Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest Overfitting" (2015).
