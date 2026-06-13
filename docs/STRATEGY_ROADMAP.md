# Strategy Roadmap — current (post-pivot)

What we're trying to do, where we are, and the ranked backlog. Reflects the **June 2026
pivot** away from the 126-param monolith to standalone, individually-optimized strategies.
Supersedes the root `ROADMAP.md` (which describes the pre-pivot Flask/5-pillar/ML-sweep era).

_Written 2026-06-13 from a full re-read of the concept pages, RC_STRATEGY_STATISTICS.md,
ANTI_OVERFITTING_PLAYBOOK.md, and the deployed code._

---

## The goal (unchanged)

Fully autonomous day-trading of Ross Cameron's playbook. Remove emotional trading entirely
via automation. The corpus proves the thesis: trades **without** behavioral deviation win
73.1% vs **49.2%** with — and the system structurally *cannot* FOMO / revenge-trade / oversize.
That gap is the edge.

## What we're actually doing now

A **two-strategy stack**, each its own pure pipeline (engine = shared pure fns called by both
sim and live; ~13 tunable params each; walk-forward train/select/seal):

| Slot | Strategy | Corpus WR | Window | Status |
|------|----------|-----------|--------|--------|
| 1 | Opening Bell Scalp (gap-and-go) | 78.2% (#1) | 9:30–9:40 | deployed (paper) |
| 2 | VWAP Reclaim | 72.0% (#4) | 10:00–11:30 | deployed (paper), ⚠️ STALE config |

Both are top-tier picks by win rate. Both news-gated (news 73.4% vs 60.7% no-news). The
methodology is sound — the month of overfitting pain (126 knobs, no holdout, peak-select) is
behind us. **The risk now is data integrity and coverage, not method.**

## The discipline (non-negotiable guardrails)

Every strategy change goes through: cut params → walk-forward (2021-23 train / 2024 select /
**2025 sealed, scored once**) → plateau-select → MC-bootstrap validate distribution. A point
estimate is never enough; the sealed median across the validate distribution is the only number
trusted live. See `docs/ANTI_OVERFITTING_PLAYBOOK.md`. **Do not bolt unvalidated logic onto a
deployed strategy** — it invalidates the sealed result.

---

## Ranked backlog (corpus-grounded)

### P0 — data integrity (blocks trustworthy live)
1. **Data versioning / sealed-test fingerprint.** VWAP trial 173's sealed-2025 (+$2,669/90%)
   does NOT reproduce on today's DB (+$19/40%) — the DB mutated (backfill/repopulation) after
   the sealed run. A sealed test is only valid on frozen data. Build a fingerprint/manifest of
   the DB slice a backtest scores on, so drift is detectable and results reproducible.
   → `research/maintenance/db_fingerprint.py` (started this session).
2. **Re-validate VWAP 173 on fingerprinted current data** before any live cutover. Until a
   reproducible sealed number exists, do not trade it for real. (task #20)

### P1 — corpus-backed FIXED-RULE safety (priors, not tuned knobs → low overfit risk, but still
   re-validate the trade set before trusting live)
3. **Daily risk circuit breakers** — the single largest P&L destroyer in the corpus:
   max-loss-hit continuation = **30.9% WR / −$4,454/trade / −$1.76M total**. The rules
   (max-loss, green-to-red, give-back-half, daily-goal) are specced in
   `concept_daily_risk_rules.md` and reportedly exist "in name only" in `portfolio_manager.py`
   (log, don't enforce). The deployed scalp/VWAP runners have **no portfolio-level stop** across
   strategies. Build a pure, tested `SessionRiskState` primitive (the concept gives the exact
   spec + edge cases + priority), then wire a cross-strategy daily halt into the runners
   (needs a shared state file since scalp/VWAP are separate processes). Oversize is the earliest
   cascade signal.
4. **Market-temperature gate** — cold days **53.9% WR / −$63 avg** vs hot **71.9% / +$3,516**.
   Classify HOT/NEUTRAL/COLD/CHOP at 9:25 from gap-scanner quality + watchlist count
   (`concept_market_temperature.md`), then reduce size / tighten setup filter / earlier session
   stop on cold. Same-day read only (no multi-day carryover). Keep thresholds as fixed rules,
   not Optuna knobs.

### P2 — coverage expansion
5. **Strategy #3 = Micro-Pullback** (74.3% WR, #3, 350-trade sample). Fills the empirically-empty
   **9:40–10:00** window (the scalp's first_green caps by ~9:50; VWAP starts 10:00). Best window
   9:45–10:30. `detect_micro_pullback()` already exists in the monolith `patterns.py` — extract
   to a standalone engine + models + simulation + optuna, same template. Needs prior-momentum +
   ≤3-candle shallow pullback + decreasing volume + EMA-9 hold (+ optional MACD>0).

### P3 — Ross-fidelity upgrades (each CHANGES a strategy → full re-optimization)
6. **VWAP scaled exits + extended-hold trail.** Concept says extended holds are this pattern's
   whole edge (highest avg result, 11.8% run EOD); the fixed 8.87% target forecloses it. Add
   scale-50%-at-T1 + trail-above-VWAP. Biggest upside, but a strategy change.
7. **Scalp entry: breakout-candle volume confirmation** (>1.5× avg, currently absent) and/or
   **pm-high-anchored stop** (Ross uses the broken level as support, not a flat %).
8. **(Optional) vwap-break/curl** — higher WR (78.1%) + 2.7× the sample of reclaim, but requires
   anticipation rather than confirmation; only if it can be mechanized.

### Known cleanups (non-blocking)
- 6 failing legacy-monolith tests (incl. `indicators.calculate_ema` returning a trailing SMA,
  not an EMA) — deprecated path; delete with the monolith or fix if revived.
- `.gitignore` sweep for regenerable run-state (backfill progress JSON, optimizer scratch).
- `GITHUB_TOKEN` on Render + re-push data branch (floats) for parity fixes #2/#3 to go live.

---

## Why the order

Data integrity (P0) first: no strategy work is trustworthy until a sealed number is reproducible.
Then the two fixed-rule safety nets (P1) — they protect a real-money account and are the corpus's
highest-conviction findings, cheap to add as priors. Then coverage (P2, micro-pullback) to fill
the 9:40–10:00 hole. Fidelity upgrades (P3) last because each is a full re-optimization cycle.
