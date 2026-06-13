# Project History & Component Ledger — jTrader

Living record of what was built, when, why — plus a component index and file-hygiene flags.
Maintained by the **historian** skill (`.claude/skills/historian`). Bootstrap pass written manually
2026-05-31 from git history + session context; incremental passes append from `git log`.

**History watermark (last commit folded in):** `b75b9a0` (2026-06-12)

---

## Timeline

### Phase 1 — Corpus + first patterns (2026-05-06 → 05-07)
- `a34b994` 05-06 — TRADE_MECHANICS enrichment pass 1 across all 19 transcript chunk files.
- `9d08944`/`1a6a254` 05-06 — first 5 jTrader concept pages from enrichment.
- `44c0423` 05-06 — **gap-and-go** pattern detector, wired into entry engine.
- `0f7f61f` 05-07 — **vwap-reclaim** detector wired in.
- `fad29ba` 05-07 — reorganized Ross Cameron video/corpus folder structure.
- `23b217e`/`cfc978e`/`966b348` 05-07 — 12 more concept pages (framework / pattern / analysis).

### Phase 2 — Risk, temperature, refactor (2026-05-20)
- `323ec41` — enforce daily risk rules + fix MACD gate + enable float filter.
- `d036633` — EMA-9 gate, time-decay at 11am, max-trades/day.
- `1f86931` — **market temperature** + first PositionManager refactor.

### Phase 3 — Strategy build-out + broker layer (2026-05-22)
- `f3a99eb` — all 17 concept pages updated against the full 1,799-session corpus (authoritative).
- `cf1a431` — fix 9 trading-logic gaps + **Tradier broker abstraction layer** (broker/base, tradier).
- `8c93c63` — **add-on / pyramid engine** (add_on_engine.py, GAP-03).
- `7401d8d` — **composite entry scoring engine** (scoring_engine.py).
- `1c9f802` — 5 strategy gaps: dip-buy 3 Tricks, VWAP break/curl, news cache, Optuna scoring, cushion sizing.
- `08cf474` — 4 exit/sizing fixes: MACD-flip qty, T2 stop migration, float buckets, temp snapshot timing.
- `d7bd070` — sync Optuna search space with the updated logic.
- `258eb56` — cache per-minute avg_vols in `_DATA_CACHE` (Optuna speed).

### Phase 4 — Data backfill + objective + audits (2026-05-29, folded into `c2fa532`)
- rel_vol_30d **backfill 2021→2025** into `stock_candles_1m` (research/maintenance/backfill_rel_vol_historical.py).
- DB **compress + cleanup** 154 GB → 45 GB (compress_and_cleanup.py).
- Optimizer **objective → `consistency`** (green-day + payoff + drawdown; objective_functions.py) — replaces raw total_pnl.
- `entry_gate.py` (risk-rule enforcement extracted), engine audit (ENGINE_AUDIT), MED fixes M2-M5,
  H1 (partial-scale double-count), corpus threshold audit (CORPUS_THRESHOLD_AUDIT), exit audit.

### Phase 6 — Intraday momentum scanner (2026-06-01)
- `8ce62f1` — **`momentum_scanner.py`**: pure `qualifies_momentum()` + `MomentumScanConfig` (38-test truth-table).
- `e814136` — `Orchestrator._scan_for_entry`: `_high_of_day` state (time-forward HOD); scanner pre-filter replaced by `qualifies_momentum()`.
- `eae054e` — golden re-baseline (behavior changed: realistic discovery) + parity PASS.
- `d1cd5cd` — `live_scanner`: `_run_intraday_momentum_scan()` (6 scan times 9:35-10:45; cap=50; seeds bar history); intraday trigger in `process_bar`.
- `b7e50ec` — `MomentumScanConfig` wired through `RunConfig`→`simulate_one`→`SimulationRunner`→`Orchestrator`; `optuna_run.py` adds Category M search space (m_min_intraday_gain, m_scan_end_hour, m_hod_tol).

### Phase 5 — Orchestrator migration + parity (2026-05-30 → 05-31)
- `c2fa532` 05-30 — **migrate per-minute decision logic into the shared `Orchestrator`** (sim/live one engine);
  H0 fix (sim MACD was dead: BAR_HISTORY_SIZE 30→40 + wrong key). golden-day regression byte-identical.
- `5711b05` 05-30 — **parity harness** (parity_check.py): proved sim == live on all 5 golden days. Fixed 3
  live bugs it surfaced: add-on 3× cap, `t1_hit` never set, M1/H1 add-on P&L accounting.
- `b0f8c66` 05-30 — **wire live_scanner to the Orchestrator** (flag-gated `_use_orchestrator`, default OFF).
- `8dfc583` 05-31 — batching unit test; logged the intraday high-day-momo scanner gap. **Merged to main.**

### Phase 7 — Parity hardening + optimizer speed + param locking (2026-06-01 → 06-02)
- `ddfa1fe` 06-01 — docs-only: PROJECT_HISTORY updated for Phase 6 (no functional change).
- `4e6c4fe` 06-01 — **bug fix**: intraday momentum scan now runs every minute 9:30-11:00 (was every 15 min); scan gate corrected.
- `de7983f` 06-01 — **bug fix**: `_build_hot_symbols` superset filter now includes `min_intraday_gain` from Optuna search space (was missing → hot-symbol list too broad).
- `3f8a04d` 06-01 — **~13× optimizer speedup**: 3 fixes — memory cache persisted across trials, `_DATA_CACHE_MAX` 300→1500 (no LRU eviction), misc I/O reduction.
- `3fc82ce` 06-01 — fix 7 remaining sim/live divergences; add pre-paper-trading TODO list.
- `34ba044` 06-02 — remove dead gates; add **parity audit system** (`parity_audit.py`, `parity_baseline.json`, `.hooks/pre-commit-parity`); Optuna cleanup.
- `2bad0d7` 06-02 — fix all 7 remaining parity divergences → **26/26 parity checks pass** (`PARITY_AUDIT.md`).
- `519ebee` 06-02 — `--lock-file` flag in `optuna_run.py`; **`locked_params_v1.json`** (45 params locked from stability/plateau analysis).
- `f556bf8` 06-02 — **plateau + stability analysis** (`plateau_analysis.py`, `param_stability.py`, `run_holdout.py`); **`locked_params_v2.json`** (56 params locked; adds m_* momentum params).
- `d32f123` 06-02 — **stratified day sampler** (`date_sampler.py`): Optuna now draws 1 day/week across 5-yr range → 259 days/trial; removes recency bias.

### Phase 8 — Objective hardening + Strategy #1 Opening Bell Scalp (2026-06-04 → 06-08)
- `ca60ea8` 06-04 — variance penalty added to consistency objective + `--no-median-prune` flag (objective stability).
- `4c24efc` 06-04 — exclude variance penalty from intermediate pruner objectives (pruner was double-counting it).
- `71c093c` 06-05 — same fix follow-up: keep variance out of pruning-stage objectives.
- `5faa2a6` 06-08 — **Opening Bell Scalp strategy #1** (`scalp_engine.py`, `scalp_models.py`, `scalp_ranker.py`, `scalp_simulation.py`, scalp Optuna pipeline) — profitable across all OOS years.

### Phase 9 — Live deployment + paper trading (Render/Tradier) (2026-06-09 → 06-10)
- `f4e0d45`/`00d8363` 06-09 — **live scalp runner** (`live_scalp_runner.py`) for paper/live via Tradier; sandbox for both data+orders in paper.
- `5b27297` 06-09 — jTrader **deployment infrastructure** (Dockerfile, requirements-deploy, render.yaml, api/ service) + fixes.
- `c9c8195` 06-09 — move render.yaml to repo root (Render Blueprints requirement).
- `c8b183f`/`30713d9`/`4e0fb2c`/`a14817c` 06-10 — `/logs` ring buffer, manual `POST /trigger` endpoint, root logger INFO fix, circular-import fix.
- `210c9ec` 06-10 — fix scheduler firing at 1:55 PM ET instead of 8:55 AM ET.
- `86faee9`/`035d93d` 06-10 — premarket scan every 60s (was 300s); sandbox 15-min delay offset + longer timeout.
- `6d3bbcb` 06-10 — **API-key auth on all endpoints** except `/health`.
- `cdff409` 06-10 — fix evaluate_entry/exit kwarg (`current_bar` not `bar`).

### Phase 10 — Strategy #2 VWAP Reclaim + data-feed hardening (2026-06-10 → 06-11)
- `749c0e5` 06-10 — **VWAP Reclaim strategy #2 pipeline** (`vwap_engine.py`, `vwap_models.py`, `vwap_simulation.py`, vwap Optuna pipeline).
- `ba84eff`/`5b66a32` 06-11 — batch OOS validation script + **live VWAP runner** (`live_vwap_runner.py`), chained after scalp in daily job.
- `8477af5` 06-11 — extend paper entry window to 10:00 (max_entry_bars 4→30).
- `91c3fbd` 06-11 — accept HEAD on `/health` (UptimeRobot pings with HEAD → was 405).
- `cb84da0` 06-11 — pre-bell hardening: 8:00 start, premarket bar filter, VWAP backfill.
- `f5ccb3c` 06-11 — **live bar capture** to JSONL + `/bars_dump` endpoint + DB pull script (live/sim parity data).
- `f209a63` 06-11 — use **Tradier production token** for data feed in paper mode (sandbox blind premarket).
- `bef4123`/`0037b80`/`c9d3371` 06-11 — **3-pass mover-targeted historical backfill** scripts; bound prev-close/volume lookbacks, exclude test symbols; premarket hour rollup param fix.

### Phase 11 — Live/sim parity validation + news capture (2026-06-12)
- `080a09d` 06-12 — delay engine clock 15 min in paper mode to match sandbox fills.
- `6509dc3` 06-12 — verify order state after failed cancel → adopt raced fills.
- `3525709` 06-12 — **daily session report** (`session_report.py`): paper vs live-counterfactual P&L.
- `f7a6708` 06-12 — **sim-replay parity tool** (`sim_replay.py`): run simulator on live session bars.
- `734f731` 06-12 — **daily validation pipeline** (`daily_validation.py`): rebuild a session via Alpaca backfill + re-sim to prove historical data ≈ live reality; Alpaca SIP clamp fix.
- `4d71f2c` 06-12 — **live news capture** (`backfill_news.py`) + validation defaults to yesterday.
- `446b27d` 06-12 — shared candidate screen: top-20 cut + 1000% gap cap (selection parity).
- `b75b9a0` 06-12 — docs: REL_VOL_LIVE_PARITY_DESIGN — baseline export via data branch.

---

## Component Index
Status: 🟢 active · 🟡 partial/transitional · ⚫ deprecated (safe to remove)

### The engine (`production/trading/` — ONE copy, sim + live share it)
| File | Purpose | Status | Since |
|---|---|---|---|
| `orchestrator.py` | The one per-minute decision pipeline (`on_minute`). Broker-agnostic. Tracks `_high_of_day` per symbol; scanner mode uses `qualifies_momentum()`. | 🟢 | e814136 |
| `momentum_scanner.py` | Pure `qualifies_momentum()` — 6 corpus gates (G1-G6). ONE shared fn for sim + live discovery parity. | 🟢 | 8ce62f1 |
| `execution.py` | Broker Protocol (the only order interface the engine touches) | 🟢 | c2fa532 |
| `entry_engine.py` / `exit_engine.py` / `add_on_engine.py` | pure evaluators | 🟢 | phases 1-3 |
| `scoring_engine.py` | composite entry score (sizing + threshold) | 🟢 | 7401d8d |
| `patterns.py` / `indicators.py` | pattern detectors + TA | 🟢 | phase 1+ |
| `market_temperature.py` | HOT/NEUTRAL/COLD/CHOP state machine | 🟢 | 1f86931 |
| `portfolio_manager.py` | daily risk rules (max-loss / green-to-red / give-back) | 🟢 | 323ec41 |
| `trading_engine.py` | `Trade` + `PositionManager` (fills, balance, daily loss) | 🟢 | 1f86931 |
| `sizing.py` | `compute_shares` + `cushion_size_multiplier` (single source) | 🟢 | c2fa532 |
| `entry_gate.py` | pure capacity→session-stop→risk-rule entry gate | 🟢 | c2fa532 |
| `data_feed.py` | DataFeed Protocol | 🟢 | c2fa532 |
| `models.py` | all config dataclasses (Scanner/Entry/Exit/Scoring/AddOn/Temp) | 🟢 | phase 1+ |
| `order_manager.py` | `OrderExecutor` + `LiveTradeManager` (real broker lifecycle) | 🟢 | cf1a431 |
| `live_broker.py` | LiveBroker (Broker over LiveTradeManager) | 🟢 | c2fa532 |
| `live_scanner.py` | live runtime: premarket scan + **intraday momentum scan** (9:35-10:45, cap=50) + (flag-gated) orchestrator path | 🟡 flip default-OFF | d1cd5cd |
| `broker/base.py`,`broker/tradier.py` | broker/data-feed interfaces + Tradier impl (prod-token data feed in paper) | 🟢 | cf1a431 |
| `bar_capture.py` | records every live bar to daily JSONL (`bars_YYYYMMDD.jsonl`) for live/sim parity; news capture | 🟢 | f5ccb3c |

### Strategy #1 — Opening Bell Scalp (`production/trading/`, LIVE)
| File | Purpose | Status | Since |
|---|---|---|---|
| `scalp_engine.py` | Opening Bell Scalp entry/exit evaluator (strategy #1) | 🟢 | 5faa2a6 |
| `scalp_models.py` | scalp config dataclasses | 🟢 | 5faa2a6 |
| `scalp_ranker.py` | ranks gapper candidates (top-N cut) | 🟢 | 5faa2a6 |
| `live_scalp_runner.py` | live runtime for scalp (paper/live via Tradier; scheduler, premarket scan, API endpoints) | 🟢 | f4e0d45 |

### Strategy #2 — VWAP Reclaim (`production/trading/`, LIVE)
| File | Purpose | Status | Since |
|---|---|---|---|
| `vwap_engine.py` | VWAP Reclaim entry/exit evaluator (strategy #2, OOS-validated) | 🟢 | 749c0e5 |
| `vwap_models.py` | vwap config dataclasses | 🟢 | 749c0e5 |
| `live_vwap_runner.py` | live runtime for VWAP Reclaim; chained after scalp in daily job | 🟢 | 5b66a32 |

### Simulator (`production/simulator/` — adapters only, ZERO logic)
| `simulation_engine.py` | data loader + minute loop → `orch.on_minute`; SimBroker | 🟢 (+⚫ dead methods inside) |
| `sim_broker.py` | SimBroker (Broker over PositionManager) | 🟢 | c2fa532 |
| `scalp_simulation.py` | single/multi-day scalp backtest harness | 🟢 | 5faa2a6 |
| `vwap_simulation.py` | single/multi-day VWAP Reclaim backtest harness | 🟢 | 749c0e5 |

### Deployment + Dashboard (`production/api/`, repo root)
| File | Purpose | Status | Since |
|---|---|---|---|
| `api/server.py` | FastAPI service (health, logs, trigger) | 🟢 | 5b27297 |
| `api/dashboard.py` | dashboard API powering jtrader.jbirdsall.dev (watchlist/position/trades/status) | 🟢 | 5b27297 |
| `api/session_job.py` | scheduled daily session job entrypoint | 🟢 | 5b27297 |
| `Dockerfile`, `requirements-deploy.txt`, `render.yaml` | Render Blueprint deploy stack | 🟢 | 5b27297 |

### Live capture + validation (`production/data/live_capture/`)
| File | Purpose | Status | Since |
|---|---|---|---|
| `daily_validation.py` | rebuild a live session via Alpaca backfill + re-sim → prove historical data ≈ live reality | 🟢 | 734f731 |
| `session_report.py` | daily paper vs live-counterfactual P&L report (run BEFORE deploys) | 🟢 | 3525709 |
| `sim_replay.py` | run the simulator on captured live-session bars | 🟢 | f7a6708 |
| `pull_live_bars.py` | pull `/bars_dump` JSONL → TimescaleDB (stock_candles_live_1m) | 🟢 | f5ccb3c |
| `data/backfill/backfill_news.py` | live/historical news capture | 🟢 | 4d71f2c |

### Research tooling (`research/optimizer/`, `research/maintenance/`, `research/analysis/`)
| `optimizer/simulate_one.py` | run a date range → metrics (objective=`consistency`) | 🟢 |
| `optimizer/optuna_run.py` | the optimizer; `--lock-file` support, Category M (momentum) search space | 🟢 |
| `optimizer/objective_functions.py` | selectable objective formulas (+tests) | 🟢 |
| `optimizer/golden_baseline.py` | sim regression oracle (5 golden days) | 🟢 |
| `optimizer/parity_check.py` | sim==live decision-parity harness | 🟢 |
| `optimizer/validate_findings.py` | one-off finding backtests | 🟢 |
| `optimizer/date_sampler.py` | stratified 1/week day sampler → 259 days/trial, no recency bias | 🟢 | d32f123 |
| `optimizer/param_stability.py` | per-param stability analysis across Optuna trials (CV, IQR) | 🟢 | f556bf8 |
| `optimizer/plateau_analysis.py` | plateau detection: identifies params that have converged across trials | 🟢 | f556bf8 |
| `optimizer/plateau_results.json` | output from plateau_analysis (data file, large) | 🟡 data output |
| `optimizer/run_holdout.py` | run a locked config on held-out validation dates | 🟢 | f556bf8 |
| `optimizer/locked_params_v1.json` | 45 params locked (stable/plateaued; v7 study basis) | 🟢 | 519ebee |
| `optimizer/locked_params_v2.json` | 56 params locked (extends v1; adds m_* momentum params) | 🟢 | f556bf8 |
| `optimizer/oracle_*.py`, `run_oracle_*.py` | value-of-perfect-info temperature test (UNRUN) | 🟡 needs 2021-24 universe |
| `maintenance/parity_audit.py` | automated sim==live parity audit (26 assertions; run via pre-commit hook) | 🟢 | 34ba044 |
| `maintenance/parity_baseline.json` | reference baseline for parity_audit; committed truth | 🟢 | 34ba044 |
| `maintenance/parity_results.json` | ephemeral output from parity_audit runs | 🟡 data output |
| `maintenance/backfill_rel_vol_historical.py` | rel_vol backfill (done 2021-25) | 🟢 one-shot |
| `maintenance/compress_and_cleanup.py` | DB compress/cleanup (done) | 🟢 one-shot |
| `analysis/scripts/validate_market_temperature.py` | emits hot/neutral/cold day labels | 🟢 |
| `optimizer/scalp/scalp_optuna_run.py` + `scalp_run_config.py` + `validate_batch.py` | Opening Bell Scalp Optuna search + OOS batch validate | 🟢 | 5faa2a6 |
| `optimizer/vwap/vwap_optuna_run.py` + `validate_batch.py` | VWAP Reclaim Optuna search + OOS batch validate | 🟢 | 749c0e5 |
| `data_backfill/backfill_daily_history.py` | full-universe daily-bar backfill (pass 1 of mover pipeline) | 🟢 | bef4123 |
| `data_backfill/backfill_gappers_v2.py` | mover minute bars + premarket 1h rollup (pass 2) | 🟢 | bef4123 |

### Infrastructure
| File | Purpose | Status | Since |
|---|---|---|---|
| `docs/PARITY_AUDIT.md` | Parity audit design + assertion catalogue | 🟢 | 34ba044 |
| `.hooks/pre-commit-parity` | git pre-commit hook; runs parity_audit before each commit | 🟢 | 34ba044 |
| `docs/REL_VOL_LIVE_PARITY_DESIGN.md` | design: rel-vol live parity, baseline export via data branch | 🟢 | b75b9a0 |
| `docs/ANTI_OVERFITTING_PLAYBOOK.md` | overfitting playbook (cut params, walk-forward, plateau-select) | 🟢 | phase 8 |
| `docs/DATA_SOURCES.md` | data-source status (Alpaca/Polygon/Tradier tokens, DB coverage) | 🟢 | phase 9 |

---

## Deprecations (dead — safe to delete, kept for traceability)
- ⚫ `simulation_engine._process_minute` + `_scan_for_entry` — logic moved to `orchestrator.on_minute`;
  sim now delegates. The methods are unreferenced. **Safe to delete** (golden-check after).
- ⚫ `simulation_engine._cushion_size_multiplier` — moved to `sizing.cushion_size_multiplier`.
- 🟡 `live_scanner._collect_entry_candidate` / `_execute_pending_entry` / `_try_exit` — become dead once
  `_use_orchestrator` defaults True; still the live path today. Remove after the flip is verified live.

---

## Hygiene flags — custodian pass 2026-05-31
- ✅ **RESOLVED — root-level `.py`:** moved `cancel_stop_and_sell`, `compare_entry_logic`, `compare_signals`,
  `connect_alpaca`, `diagnostic_march6`, `manual_sell_breakeven` → `research/maintenance/diagnostics/`
  (`f41cf86`). Root now = `config.py` + `run_trading.py` only.
- ✅ **RESOLVED — data/binaries out of git:** untracked ~62MB (`archive/optunaDBfiles/*.db`,
  `*_progress.json`, `database/*.log`, `optimizer/pillar23_results.db`, `analysis/gapper_universe.csv`)
  + added `.gitignore` patterns (`c977030`). Kept local; no history rewrite.
- ✅ **RESOLVED — dead sim methods:** deleted `_process_minute`/`_scan_for_entry`/`_cushion_size_multiplier`
  (`7f0c244`). golden + parity still green.
- ✅ **RESOLVED — stale docs:** `LIVE_SIM_PARITY_SPEC.md` marked DONE, `PROJECT_STATUS_AND_PLAN.md` marked
  SUPERSEDED (`6a329e3`). Kept for history.
- ⏭ **OPEN — worktree branches:** 8 `claude/*` branches at/behind main. NOT pruned — they back active
  harness worktrees (`.claude/worktrees/`); deleting risks breaking sessions. Let the harness reap them,
  or prune manually when sure they're idle.
- ⏭ **OPEN — concept pages dated 2026-05-21** describe pre-fix code in places (e.g. front_side_back_side
  MACD state) — refresh against the current engine (low priority).
- ⏭ **OPEN — `FILE_ORGANIZATION_SETUP.md`** (untracked root) — clarify purpose or place.

## Hygiene flags — custodian pass 2026-06-04
- ⚠️ **FLAG — `research/optimizer/plateau_results.json`** (committed, ~4503 lines) — data output from
  `plateau_analysis.py`; large, regenerable, changes per run. **Recommend: add to `.gitignore`** and
  delete from git history (`git rm --cached`). Keep local.
- ⚠️ **FLAG — `research/maintenance/parity_results.json`** (committed) — ephemeral output from
  `parity_audit.py`; changes every run. `parity_baseline.json` (the reference) should stay committed;
  `parity_results.json` should not. **Recommend: add to `.gitignore`**.
- ⚠️ **FLAG — `locked_params_v7_validate.json`** (untracked, created this session) — rebuilt locked-params
  file for validate3 run using Optuna API (correct boolean decoding). Not committed. If kept for
  reproducibility, commit it; otherwise it's a scratch file.
- ℹ️  **NOTE — Optuna boolean encoding**: `suggest_categorical([True, False])` stores index (0.0=True,
  1.0=False) in PostgreSQL `trial_params.param_value`. Raw SQL reads invert booleans. Always use
  `study.trials[n].params[k]` API — never raw DB values — when building `locked_params_*.json`.
  A defensive `_bool()` type-check assertion + locked-params loader validation are recommended
  but not yet implemented (see session context 2026-06-03/04).

## Hygiene flags — custodian pass 2026-06-12 (FLAG ONLY — nothing deleted/moved)
- ⚠️ **Untracked binary in repo root — `bash.exe.stackdump`** (git-bash crash dump). Junk; safe to delete. Add `*.stackdump` to `.gitignore`.
- ⚠️ **Stray backfill progress JSONs (untracked, ~13 files)** in `research/data_backfill/` (`backfill_daily_progress_*.json`, `backfill_gappers_v2_progress_*.json`). Regenerable run-state; should be gitignored (`*_progress_*.json`), not committed.
- ⚠️ **Untracked scratch locked-params** — `research/optimizer/locked_params_v8_trial180.json`, `optuna_run_log.txt`, `research/optimizer/data/findings_*.json`, `ablation/`, `data/cache/`. Optimizer scratch output; gitignore the `data/`, `ablation/`, `cache/` dirs and `*_log.txt`.
- ⚠️ **`FILE_ORGANIZATION_SETUP.md` (untracked root)** — STILL open from 05-31 pass; place under `docs/` or remove.
- ⚠️ **Untracked corpus tooling** under `Ross Cameron Day Trading Videos/` (scripts/, extractions/, prompts/, compressed transcripts/) — decide if these belong in git or stay local-only; currently neither.
- ⚠️ **Untracked diagnostics** — `research/maintenance/diagnostics/debug_vwap_jun12.py`, `profile_trial.py`. One-off debug scripts; commit if reusable, else delete.
- ⚠️ **Untracked output dirs** — `research/analysis/outputs/`, `production/data/stream/`. Ensure gitignored (analysis outputs already meant to be per FILE_PLACEMENT_GUIDE).
- ⚠️ **Untracked `docs/backtesting_pipeline_discovery.md`** — session notes; commit or fold into a permanent doc.
- ⏭ **OPEN (carried)** — concept pages dated 2026-05-21 may describe pre-fix code; refresh against current engine (low priority).
- ℹ️ **NOTE — 4 modified-but-uncommitted engine files** at pass time (`simulation_engine.py`, `orchestrator.py`, `date_sampler.py`, `scalp/validate_batch.py`) — work in progress, not folded into this history; will appear in next pass.
