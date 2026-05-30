# Market-Temperature Oracle Test

**Question:** With *perfect* (ground-truth, not predicted) knowledge of each day's market
temperature, can regime-specific configs beat one universal config? The gap is the
**ceiling** any real temperature predictor could ever capture. If the gap is ~0 (or
negative), regime-switching is not worth pursuing — **stop before building a better
predictor.** If the gap is large, that is the upper bound on the prize.

This is a value-of-perfect-information test. It deliberately uses actual labels so the
predictor's accuracy is removed from the equation.

---

## Files

| File | Role |
|---|---|
| `oracle_labels.py` | Load `hot/neutral/cold_days.csv`; one shared chronological train/test split. |
| `oracle_objective.py` | Optuna objective over an explicit day-list (reuses `optuna_run._build_config_from_trial` — identical search space). |
| `run_oracle_study.py` | Optimize ONE regime on its TRAIN days. `--regime hot\|neutral\|cold\|universal`. |
| `run_oracle_test.py` | Meta-runner: 4 studies sequentially + held-out TEST eval + verdict. |
| `simulate_one.py` | Patched: optional `dates=` param to `run_date_range` runs a scattered day-subset (non-invasive; `dates=None` = old contiguous behavior). |

Storage (separate from the main optimizer DBs):
- Optuna: `sqlite:///optimizer/oracle_optuna.db`, study `oracle_<regime>`
- Results: `optimizer/oracle_results.db`, run_id `oracle_<regime>_NNNNN`

---

## Prerequisites (ORDER MATTERS)

1. **Phase-1 DB backfill COMPLETE** (`research/maintenance/backfill_rel_vol_historical.py`).
   Do not run the oracle while the backfill is going — DB contention + RAM ceiling.
2. **Label CSVs generated.** Run the validator to produce them:
   ```
   python research/analysis/scripts/validate_market_temperature.py
   ```
   → writes `research/analysis/outputs/{hot,neutral,cold}_days.csv`.
3. **⚠️ Objective fix decided first (P1).** See `memory/optimizer_objective_fix.md`.
   The oracle's `objective` is inherited from `run_date_range`, which is currently the
   mis-specified raw `total_pnl`. Running the oracle BEFORE the objective fix lands means
   every per-regime study optimizes the tiny-win / amputated-tail regime → the ceiling
   number is polluted. **Land the objective fix, THEN run the oracle.**
   (The held-out ceiling eval itself reports raw `total_pnl` on test days — that is
   intentional: train on the robust objective, measure the ceiling in real dollars.)

---

## Run

Whole pipeline (recommended):
```
python optimizer/run_oracle_test.py --trials 300
```
(run from the `research/` directory, matching the existing optimizer cwd convention).

Per-regime manually (sequential — never simultaneous; run universal first):
```
python optimizer/run_oracle_study.py --regime universal --trials 300
python optimizer/run_oracle_study.py --regime hot       --trials 300
python optimizer/run_oracle_study.py --regime neutral   --trials 300
python optimizer/run_oracle_study.py --regime cold       --trials 300
```
Eval only (studies already done):
```
python optimizer/run_oracle_test.py --skip-optimize
```

Studies are resumable — re-running continues until `--trials` total is reached.

---

## Design notes / gotchas

- **Shared split.** One global chronological split (default `--test-frac 0.30`). Earliest
  70% = train, latest 30% = test, per day. Guarantees identical test universe:
  `universal_test == hot_test ∪ neutral_test ∪ cold_test`. `--test-frac` MUST match across
  all regimes; the meta-runner enforces this by sharing one split object.
- **No seeding.** Oracle studies do NOT seed from Trial 193 (its objective is in stale
  units once the objective changes; it is also the overfit peak we want to escape).
- **Per-regime MIN_TRADES (PENDING).** Once the objective fix adds a small-sample shrink
  (`total_trades / MIN_TRADES`), thin regimes (COLD = fewest days) would be unfairly
  crushed by a global floor. Pass a per-regime `MIN_TRADES` then. Not wired yet because
  the objective formula is not finalized.
- **Thin-regime / missing-data skew.** Labeled days with no DB data (e.g. the
  `2025-01-09` "No symbols with data" gap in `OPTIMIZER_AUDIT.md`) are silently skipped by
  `run_date_range` (`success=False → continue`). Per-regime day counts get thin fast;
  watch `days_traded vs requested`.
- **Survivorship caveat.** The pillar23 universe pre-screens *known* future gappers, so any
  ceiling the oracle reports is an upper bound on a universe that already knows the future.

---

*Cross-refs: `memory/optimizer_objective_fix.md` (P1 dependency + formula debate),
`memory/live_sim_parity_gap.md`. Built by the elated-euclid worktree session, May 29 2026.*
