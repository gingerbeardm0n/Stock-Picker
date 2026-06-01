# jTrader — Status Ledger & Work Plan (2026-05-29)

> **SUPERSEDED (2026-05-31)** by `docs/PROJECT_HISTORY.md` (timeline + component ledger) and
> `docs/AUTONOMOUS_QUEUE.md` (live work log). Kept for history; many items below are now DONE.

Reconstructed from the working session. Each item tagged:
**[DONE]** executed + verified · **[PARTIAL]** started, not finished · **[TODO]** proposed only, not begun.

---

## A. Everything we touched or proposed

### Oracle / market-temperature test
- **[DONE]** Oracle scripts written + compile-clean + dry-run passes end-to-end:
  `research/optimizer/oracle_labels.py`, `oracle_objective.py`, `run_oracle_study.py`,
  `run_oracle_test.py`, `oracle_dryrun.py`, `ORACLE_TEST_README.md`; plus the
  non-invasive `dates=` param added to `simulate_one.py::run_date_range`.
- **[TODO]** Actually RUN the oracle test. Blocked on: (1) Phase-2 backfill done,
  (2) `validate_market_temperature.py` run to emit `hot/neutral/cold_days.csv`,
  (3) objective formula chosen (below). **Needs DB.**

### Optimizer objective
- **[DONE]** `research/optimizer/objective_functions.py` + `test_objective_functions.py`
  (9/9 pass). Holds 5 selectable formulas: `total_pnl` (status quo), `drop_best_day`,
  `payoff_ratio`, `hybrid`, `consistency`, plus `worst_fold_objective` (score the worst
  of k folds = strongest anti-overfit lever).
- **[DONE]** **Decision made + WIRED (May 29): `consistency`.** `simulate_one.py:178`
  now calls `compute_objective(formula='consistency', ...)`; `total_pnl` still reported.
  Imports clean, objective tests 9/9. **[TODO]** validate effect on a real Optuna run
  (needs DB).

### Engine audit (read-only, done)
- **[DONE]** `docs/ENGINE_AUDIT_2026-05-29.md`. Findings:
  - **H0 (critical):** MACD. **RE-GROUNDED May 29:** the LIVE engine is already correct
    — `entry_engine.py:236` maps `macd_line ← macd_data['macd']`, `:276` gates on
    `macd_line <= 0` (line, not histogram). The bug was the SIMULATOR's own MACD read,
    which shouldn't exist at all (de-logic target). So M3 ≈ done in the real engine;
    the concept page `front_side_back_side.md` documents the stale broken state.
  - **H1:** `PositionManager` double-counts partial scale-outs in `current_balance`
    (inflates `avg_daily_pnl` reporting; objective unaffected). **[TODO] not fixed.**
  - **M2 [DONE May 29]** `live_scanner._run_premarket_db_snapshot` now reads
    `ScannerConfig` (price/gain/rel-vol/float) instead of module constants; py_compile
    clean. Note: no-config default now caps float at 20M (was 100M).
  - **M4 [DONE May 29]** `patterns._explain_dip_buy` rewritten to mirror the shipping
    `detect_dip_buy` (3 Tricks: news → MACD line → named support; no ema9/light-vol).
  - **M3** live MACD *diagnostic* still logs histogram not line (real gate is correct;
    logging-only) · **M5** live picks by `confidence` not entry-score · **M6** add-on
    watermark. All **[TODO]** (still non-DB).

### Sim de-logic refactor (the big architecture fix)
- **[DONE]** Increment 1 (non-DB): interfaces + sizing extraction, all import-clean:
  - `production/trading/data_feed.py` (DataFeed Protocol + bar contract)
  - `production/trading/execution.py` (Broker Protocol)
  - `production/trading/sizing.py` (`compute_shares` extracted) + `test_sizing.py`
    (**20,000 cases, 0 mismatches** vs old inline math)
  - `PositionManager` rewired to call `compute_shares` (verified identical)
  - `production/simulator/sim_broker.py` (SimBroker adapter over PositionManager)
  - `production/trading/orchestrator.py` (**skeleton — 5 NotImplementedError stubs**)
- **[DONE]** Increment 2 (May 29, non-DB): **entry-gate de-logic.** Extracted the
  Step-3 block/allow chain (capacity → temperature session-stop → portfolio risk rules)
  into pure `production/trading/entry_gate.py::entry_blocked_reason()` +
  `test_entry_gate.py` (16-combo truth table vs frozen old logic + priority — green).
  `simulation_engine.py:763` rewired to call it (behavior-identical, imports clean).
  This puts the highest-leverage discipline rule (DAILY_MAX_LOSS/GREEN_TO_RED/
  GIVE_BACK_HALF enforcement) in a SHARED tested fn so live inherits it.
- **[PARTIAL]** Plan in `docs/LIVE_SIM_PARITY_SPEC.md` (the "de-logic" plan). Steps
  remaining: 4 (move `_process_minute`/`_scan_for_entry` bodies into orchestrator — the
  orchestrator will call `entry_blocked_reason` for its pre-scan guard),
  5 (ReplayFeed), 6 (point live_scanner at orchestrator), 7 (parity_check.py).
  **Step 4 needs a golden-day baseline = DB.**

### Live ≠ Sim parity (original headline gap)
- **[TODO]** Wiring live_scanner to temperature/scoring/news/portfolio/add-ons/sizing.
  Spec exists (above); now folded INTO the de-logic refactor as its end state. Not begun.

### DB disk cleanup
- **[DONE]** `research/maintenance/compress_and_cleanup.py` (compile-clean) + queued
  task chip. Drops a duplicate 11 GB index, compresses candle hypertables
  (64 GB → ~5-8 GB), drops staging. **[TODO] run it — after backfill. Needs DB.**

### Backfill
- **[DONE]** Phase 1 (cache) complete. **[in progress]** Phase 2 fast-mode running
  (staging done, monthly applies ~mid-way as of this writing).

### Memory
- **[DONE]** `memory/optimizer_objective_fix.md` (formula debate marked OPEN/disputed),
  `memory/live_sim_parity_gap.md` (H0 MACD finding added).

### Older proposals never started
- **[TODO]** Temperature label re-weighting (cut `max_run_pct` weight, add
  yesterday's-temp feature, tune `_PARAMS`).
- **[TODO]** News-weighting A/B experiment (ScoringConfig news pts are tunable; no run).
- **[TODO]** Rotate the leaked production Tradier key (security; flagged long ago).

---

## B. Work I CAN do now WITHOUT the database (while Phase 2 finishes)

Ranked by value/safety. All are code/analysis only, no DB.

1. **Fix the pure-code MED audit findings** (1-file edits, no behavior risk to sim P&L):
   - M3: live MACD diagnostic → use MACD line (match the real gate).
   - M4: rewrite the stale dip-buy diagnostic to match the shipping detector.
   - M2: wire ScannerConfig thresholds into live premarket scan (remove hardcoded 10/5/$1-20).
2. **Fold H0 (MACD) into this worktree** as part of the orchestrator move (other session
   fixed it in-place; here it should land in the extracted indicator code).
3. **Wire the chosen objective formula** into `simulate_one.py` (after you pick) — keep
   `total_pnl` reported alongside; behavior only changes on the next optimizer run.
4. **Corpus-grounded strategy work** (your idea — load concept pages / chunk files):
   - Validate pattern thresholds + scoring weights against corpus stats.
   - Resolve the news-weighting question with corpus evidence.
   - Draft the temperature label re-weighting from the corpus.

> NOTE on context loading: the **17 concept pages** are the distilled corpus truth and
> are small enough to hold in context — load those. The **19 chunk files** are large and
> mostly redundant with the concept pages; grep them on-demand for specific numbers
> rather than loading all into context (cheaper, and avoids drowning signal).

---

## C. Work that MUST wait for the DB
- Run the oracle test (needs labels + chosen objective).
- Refactor steps 4-7 (need golden-day regression baseline).
- Fix H1 (do it while building the real SimBroker accounting, verified by golden days).
- Run `compress_and_cleanup.py`.
- Any optimizer run / validation.

---

## D. Suggested sequence after compaction
1. Load the 17 concept pages into context.
2. Knock out B-1 (MED code fixes) + B-2 (fold H0) — safe, no DB.
3. You pick the objective formula → I wire it (B-3).
4. Corpus-grounded analysis (B-4) → concrete tuning proposals.
5. When Phase 2 + cleanup done → oracle run, refactor step 4+, H1 fix.
