# Project History & Component Ledger — jTrader

Living record of what was built, when, why — plus a component index and file-hygiene flags.
Maintained by the **historian** skill (`.claude/skills/historian`). Bootstrap pass written manually
2026-05-31 from git history + session context; incremental passes append from `git log`.

**History watermark (last commit folded in):** `32a5777` (2026-06-23)

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

### Phase 12 — Rel-vol live parity + parity audit + record-keeping (2026-06-12 → 06-13)
- `73bf2a5` 06-12 — **live rel-vol from shipped baseline** (`rel_vol_live.py`, Gap #1): fetch 30-day-avg denominator from the `data` branch, divide live quote volume; sim-matching 10.0 fallback. Tradier `QuoteResult.volume` added.
- `cfce03c` 06-12 — baseline fetch sends `GITHUB_TOKEN` (repo is private).
- `2438523` 06-13 — thread-safe symbol table + `_DATA_CACHE` locks (cache cap 250→1500); NaN rel_vol guard + bypass gate when avg_vol=0 (orchestrator); date blacklist 2021-01-04 + `extra_blacklist`; `validate_batch` CLI trial override; export `git add -f`.
- `ff219c2` 06-13 — **date-param on `/bars_dump` + `/news_dump`** (`read_bars_for_date`/`read_news_for_date`/`available_dates`) so a prior day's capture can be pulled before a redeploy wipes ephemeral disk; `pull_live_bars --date`.
- `4ae4cf7` 06-13 — **parity audit fixes** (3 gaps): shared news gate `has_news_catalyst()`/`NEWS_CATALYST_TIERS` (live had excluded tier3); ship float baseline + live scalp float filter; VWAP rel-vol numerator reconstructed as cumulative-through-9:25 (was instantaneous quote vol, 2-3x inflated). See `docs/PARITY.md`.
- Record-keeping overhaul (uncommitted docs): new `docs/PARITY.md` (sim/live gap ledger), `STATUS.md` (current-state snapshot); `MEMORY.md` slimmed 411→~62 lines (legacy detail → `memory/archive_legacy_monolith.md`).

### Phase 13 — Alpaca paper trading migration + scanner bug fix (2026-06-13 → 06-17)
- `89f5c82`/`81c1a44`/`fff3c42`/`009355c` 06-13 — docs+tooling: parity ledger, DB fingerprint, strategy roadmap; strategy #3 micro-pullback pipeline (models + engine + sim + optuna + tests).
- `aec9d07` 06-13 — freeze VWAP sealed-2025 data fingerprint baseline.
- `2825c65` 06-13 — **session persistence**: `session_persistence.py` persist live trades to DB via `session_report.py`.
- `3e6ab2f` 06-13 — archive 17 legacy monolith files → `archive/legacy_monolith/`; drop retention policies.
- `8a2b766` 06-13 — rewrite parity audit for active pipelines (scalp/VWAP, not monolith).
- `f06a62d` 06-14 — **unified `/dashboard` endpoint** + rich candidate serialization in `session_job.py` / `dashboard.py`.
- `05f4acf` 06-15 — scanner gap-filter diagnostics added to both runners.
- `8643b17` 06-15 — **multi-source news waterfall**: Finnhub → Marketaux → Alpaca (`news_fetcher.py`).
- `89ea43d` 06-15 — auto-persist session data to TimescaleDB after trading.
- `a25f52d` 06-15 — **GitHub Actions rel-vol baseline builder** (no DB required, `build_baseline_cloud.py`).
- `07f767c` 06-16 — GitHub Actions daily session capture at 1 PM ET (`session-capture.yml`).
- `076e9eb` 06-16 — fix empty `active_gapper_symbols.json` edge case in rel-vol workflow.
- `a0c1417` 06-16 — lower `min_gap_pct` 11.65→5.0 (scalp) / 9.41→5.0 (VWAP) for wider universe.
- `39bfe0b`/`4029425`/`57b7d45` 06-16 — merge commits from worktrees.
- `ec5e02c` 06-17 — **bid/ask midpoint fallback** when Tradier `last` is stale in premarket scan.
- `ab7a3c1` 06-17 — **junk spread filter**: skip quotes where `ask/bid > 3x` (sandbox garbage).
- `79d96d1` 06-17 — **major broker switch**: paper orders → Alpaca paper (`AlpacaBroker(paper=True)`); double-sell bug fix (check stop status before market sell); VWAP multi-trade loop (one-and-done removed, `_record_trade()` resets state); log buffer 100→2000 lines.
- `828170f` 06-17 — session capture cron 1 PM → 12 PM ET.
- `0efea44` 06-17 — **separate Alpaca paper keys** (`APCA_PAPER_KEY_ID`/`APCA_PAPER_SECRET_KEY`) from live data keys; `Config._make_alpaca_broker()` routes by mode.
- `46e5d00` 06-17 — **`PAPER_STARTING_BALANCE`** env var: runners use $5k for position sizing regardless of Alpaca paper balance ($100k default); `research/reset_paper_account.py` confirms no API reset endpoint.
- `395a05d` 06-17 — **fix rel-vol CI**: force-push on orphan branch was wiping session files; now mirrors session-capture pattern (checkout existing data branch, normal push).
- `26d10ec` 06-17 — **critical scanner fix**: `AlpacaDataFeed.get_quotes()` returned `prev_close=0.0` → all symbols skipped → 0 gappers; both runners now call `get_prior_closes()` first and patch; `last=midpoint` not `ask`; VWAP scanner gains midpoint fallback.

### Phase 14 — Production hardening + all 3 runners live (2026-06-17 → 06-23)

**2026-06-17**
- `f8439ff` — fix(dashboard): persist shares/stop/bars_held + VWAP multi-trade P&L in state.json
- `9066e1e` — chore: daily session start moved 8:00 AM → 7:00 AM ET (premarket scan now starts 7 AM)

**2026-06-18**
- `6edb58b` — feat(scanner): news enrichment expanded top-20 → top-50 gappers
- `0e2a6d1` — fix(dashboard): write state.json during premarket scan loop (not just post-session)
- `8e9addf` — feat(scalp): multi-candidate entry — watch top 10, enter up to 3 concurrent positions
- `3b694cc` — fix(rel-vol): `compute_rel_vol()` called during `scan_premarket()` (was hardcoded 10.0)
- `413227d` — fix(vwap): entry retry with market-order fallback on missed limit fill (2% slippage cap)
- `00ea1fd` — feat: **Strategy #3 live micro-pullback runner** (`live_micro_pullback_runner.py`), 9:30-11:30 window, active-position blocking via `_positions_lock.py`
- `2de16ba` — feat(micro-pullback): trial #159 locked for paper trading

**2026-06-19**
- `9d01ea4` — feat(micro-pullback): swap live config trial 159→167

**2026-06-22**
- `858bd5d` — fix: handle `BarSet` response from Alpaca SDK in `get_bars_since_4am` + `get_prior_closes`
- `9e030b0` — feat(vwap): deploy trial 56 config live (97% WR, 12× PF on 2025 sealed set)
- `0556574` — feat(infra): Neon PostgreSQL as primary rel_vol baseline store (`_fetch_from_neon` added to `rel_vol_live.py`)
- `51b02b1` — fix: drop `updated_at` from Neon INSERT (let DB default handle it)
- `85cfdfa` — feat(automation): GitHub Actions runner watchdog (`runner-watchdog.yml`) — POST /trigger at 6:50 AM ET if APScheduler misses
- `9fc3c70` — fix(runners): 3 bugs — JSON crash on non-dict candidate, float-bypass log warning, `_positions_lock` race on startup
- `94db5c3` — feat(floats): yfinance float data pipeline — first-seen + weekly refresh, stored in Neon `rel_vol_baselines.float_shares`
- `95d3ebd` — feat(journal): daily markdown trade journal (`generate_journal.py`) from session JSON

**2026-06-23**
- `0efa80a` — fix(runners): 4 bugs — dashboard 500 (wrong import alias), sub-penny Tradier rejection (`round(entry_price,2)` in all 3 runners), Marketaux removed from news waterfall, `psycopg2-binary`/`yfinance` added to `requirements-deploy.txt`
- `32a5777` — feat(runners): multi-position VWAP refactor (`positions: dict` replaces single-pos fields); premarket hybrid scan (60s watchlist re-quote + 5-min full scan); dashboard updated for multi-position state

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
| `bar_capture.py` | records every live bar + news to daily JSONL (`bars_/news_YYYYMMDD.jsonl`); `read_*_for_date`/`available_dates` for prior-day pulls | 🟢 | f5ccb3c |
| `rel_vol_live.py` | live rel-vol parity: fetch 30-day baseline (+floats) from `data` branch, `compute_rel_vol` w/ 10.0 fallback | 🟢 | 73bf2a5 |

### Strategy #1 — Opening Bell Scalp (`production/trading/`, LIVE)
| File | Purpose | Status | Since |
|---|---|---|---|
| `scalp_engine.py` | Opening Bell Scalp entry/exit evaluator (strategy #1) | 🟢 | 5faa2a6 |
| `scalp_models.py` | scalp config dataclasses | 🟢 | 5faa2a6 |
| `scalp_ranker.py` | ranks gapper candidates (top-N cut) | 🟢 | 5faa2a6 |
| `live_scalp_runner.py` | live runtime for scalp (paper/live via Alpaca paper; premarket scan with prior-close fetch, midpoint fallback, double-sell guard) | 🟢 | f4e0d45 |

### Strategy #2 — VWAP Reclaim (`production/trading/`, LIVE)
| File | Purpose | Status | Since |
|---|---|---|---|
| `vwap_engine.py` | VWAP Reclaim entry/exit evaluator (strategy #2, OOS-validated) | 🟢 | 749c0e5 |
| `vwap_models.py` | vwap config dataclasses | 🟢 | 749c0e5 |
| `live_vwap_runner.py` | live runtime for VWAP Reclaim; chained after scalp; multi-trade loop, prior-close fetch, midpoint fallback | 🟢 | 5b66a32 |

### Simulator (`production/simulator/` — adapters only, ZERO logic)
| `simulation_engine.py` | data loader + minute loop → `orch.on_minute`; SimBroker | 🟢 (+⚫ dead methods inside) |
| `sim_broker.py` | SimBroker (Broker over PositionManager) | 🟢 | c2fa532 |
| `scalp_simulation.py` | single/multi-day scalp backtest harness | 🟢 | 5faa2a6 |
| `vwap_simulation.py` | single/multi-day VWAP Reclaim backtest harness | 🟢 | 749c0e5 |

### Deployment + Dashboard (`production/api/`, repo root)
| File | Purpose | Status | Since |
|---|---|---|---|
| `api/server.py` | FastAPI service (health, logs, trigger) | 🟢 | 5b27297 |
| `api/dashboard.py` | dashboard API; unified `GET /dashboard` endpoint + stage inference; log ring buffer 2000 lines | 🟢 | 5b27297 |
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

### New in Phase 14
| File | Purpose | Status | Since |
|---|---|---|---|
| `production/trading/live_micro_pullback_runner.py` | Live runner for Strategy #3 Micro-Pullback (9:30-11:30); trial 167; round(entry_price,2) sub-penny fix | 🟢 | 00ea1fd |
| `production/trading/_positions_lock.py` | Thread-safe cross-strategy position lock — prevents VWAP + micro-pullback double-entering same symbol | 🟢 | 00ea1fd |
| `production/data/live_capture/generate_journal.py` | Generates daily markdown trade journal from session JSON | 🟢 | 95d3ebd |
| `.github/workflows/runner-watchdog.yml` | GitHub Actions watchdog: POST /trigger at 6:50 AM ET if Render APScheduler missed the 7 AM job | 🟢 | 85cfdfa |

**Phase 14 updates to existing components:**
- `live_vwap_runner.py` — major refactor: `positions: dict` (multi-position), per-symbol entry/exit, `completed_trades` list; trial 56 config deployed
- `live_scalp_runner.py` — hybrid premarket scan (60s watchlist + 5min full); multi-candidate up to 3 concurrent; `round(entry_price,2)` sub-penny fix
- `live_micro_pullback_runner.py` — `round(entry_price,2)` sub-penny fix
- `rel_vol_live.py` — Neon primary source `_fetch_from_neon()`; `float_shares` column added to query
- `build_baseline_cloud.py` — Neon upsert; yfinance float data fetch
- `news_fetcher.py` — Marketaux removed (rate limit always exhausted); waterfall now Finnhub → Alpaca only
- `dashboard.py` — fixed `TRIAL_173_CONFIG` import → `TRIAL_56_CONFIG`; multi-position `vwap_position` block; Decision Transparency dashboard fully wired
- `session_job.py` — parallel micro-pullback thread; `positions` field in VWAP state write; `_serialize_candidates()` saves full candidate dicts (not symbol strings)
- `requirements-deploy.txt` — `psycopg2-binary>=2.9` + `yfinance>=0.2` added (Render uses this file, not root `requirements.txt`)

### New in Phase 13
| File | Purpose | Status | Since |
|---|---|---|---|
| `production/api/session_persistence.py` | persist live trades/bars/news to TimescaleDB post-session | 🟢 | 89ea43d |
| `production/data/live_capture/build_baseline_cloud.py` | GitHub Actions rel-vol baseline builder (no DB) | 🟢 | a25f52d |
| `production/trading/micro_pullback_engine.py` | Strategy #3 micro-pullback evaluator | 🟡 research | 009355c |
| `production/trading/micro_pullback_models.py` | Strategy #3 config dataclasses | 🟡 research | 009355c |
| `production/simulator/micro_pullback_simulation.py` | Strategy #3 backtest harness | 🟡 research | 009355c |
| `research/optimizer/micro_pullback/` | Strategy #3 Optuna pipeline | 🟡 research | 009355c |
| `research/maintenance/db_fingerprint.py` | DB fingerprint for sealed-test reproducibility | 🟢 | fff3c42 |
| `research/reset_paper_account.py` | Alpaca paper account reset utility (confirms no API endpoint for custom balance) | 🟢 one-shot | 46e5d00 |
| `.github/workflows/rel-vol-baseline.yml` | Daily 4:30 PM ET rel-vol baseline update to data branch | 🟢 | a25f52d |
| `.github/workflows/session-capture.yml` | Daily 12 PM ET pull session data from Render → data branch | 🟢 | 07f767c |
| `production/trading/broker/alpaca.py` | AlpacaBroker (paper/live) + AlpacaDataFeed (midpoint quotes, prior-close-aware) + AlpacaBarStream | 🟢 | 79d96d1 |

### Infrastructure
| File | Purpose | Status | Since |
|---|---|---|---|
| `docs/PARITY_AUDIT.md` | Parity audit design + assertion catalogue | 🟢 | 34ba044 |
| `.hooks/pre-commit-parity` | git pre-commit hook; runs parity_audit before each commit | 🟢 | 34ba044 |
| `docs/REL_VOL_LIVE_PARITY_DESIGN.md` | design: rel-vol live parity, baseline export via data branch | 🟢 | b75b9a0 |
| `docs/ANTI_OVERFITTING_PLAYBOOK.md` | overfitting playbook (cut params, walk-forward, plateau-select) | 🟢 | phase 8 |
| `docs/DATA_SOURCES.md` | data-source status (Alpaca/Polygon/Tradier tokens, DB coverage) | 🟢 | phase 9 |
| `docs/PARITY.md` | sim/live parity ledger — every divergence + status (fixed/open/inherent) | 🟢 | phase 12 |
| `STATUS.md` (root) | current-state snapshot: deployed / live configs / next actions / blockers | 🟢 | phase 12 |
| `production/data/live_capture/export_rel_vol_baseline.py` | export rel-vol baseline + floats → `data` branch (`--push`) | 🟢 | phase 11-12 |

---

## Deprecations (dead — safe to delete, kept for traceability)
- ⚫ `simulation_engine._process_minute` + `_scan_for_entry` — logic moved to `orchestrator.on_minute`;
  sim now delegates. The methods are unreferenced. **Safe to delete** (golden-check after).
- ⚫ `simulation_engine._cushion_size_multiplier` — moved to `sizing.cushion_size_multiplier`.
- 🟡 `live_scanner._collect_entry_candidate` / `_execute_pending_entry` / `_try_exit` — become dead once
  `_use_orchestrator` defaults True; still the live path today. Remove after the flip is verified live.

---

## Hygiene flags — custodian pass 2026-06-23
- 🚩 **`research/maintenance/cleanup.log`** — log file committed to git; should be gitignored (`.log` pattern already in `.gitignore` but file may be tracked). Verify with `git ls-files research/maintenance/cleanup.log`.
- 🚩 **`research/maintenance/backfill_daily_gappers_cache.py`** — untracked file (shows in `git status ??`). Needs to be committed or added to `.gitignore` depending on whether it's active tooling or a scratch script.
- 🚩 **`bash.exe.stackdump`** — untracked root-level crash dump from git-bash. Safe to delete / gitignore.
- 🚩 **`production/trading/micro_pullback_engine.py` + `micro_pullback_models.py`** — marked 🟡 research in Phase 13. Now that `live_micro_pullback_runner.py` is deployed live, verify these are the canonical engine files (not duplicates of what the runner imports).
- 🚩 **Monolith path** (`run_trading.py`, `live_scanner.py` with `_use_orchestrator=False`) — with 3 standalone strategy runners live, the old `run_trading.py` entry point is likely dead. Verify nothing calls it before removing.
- 🚩 **`production/api/server.py`** — may duplicate endpoint logic with `dashboard.py`. The `/dashboard` endpoint was built in `dashboard.py`; confirm `server.py` doesn't have a stale `/dashboard` route.
- ✅ **RESOLVED — root-level `.py`:** moved `cancel_stop_and_sell`, `compare_entry_logic`, `compare_signals`, `connect_alpaca`, `diagnostic_march6`, `manual_sell_breakeven` → `research/maintenance/diagnostics/` (`f41cf86`). Root now = `config.py` + `run_trading.py` only.
- ✅ **RESOLVED — data/binaries out of git:** untracked ~62MB (`archive/optunaDBfiles/*.db`, `*_progress.json`, `database/*.log`, `optimizer/pillar23_results.db`, `analysis/gapper_universe.csv`) + added `.gitignore` patterns (`c977030`). Kept local; no history rewrite.
- ✅ **RESOLVED — dead sim methods:** deleted `_process_minute`/`_scan_for_entry`/`_cushion_size_multiplier` (`7f0c244`). golden + parity still green.
- ✅ **RESOLVED — stale docs:** `LIVE_SIM_PARITY_SPEC.md` marked DONE, `PROJECT_STATUS_AND_PLAN.md` marked SUPERSEDED (`6a329e3`). Kept for history.

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

## Hygiene flags — custodian pass 2026-06-13 (FLAG ONLY — nothing deleted/moved)
- ✅ **RESOLVED — the 4 engine files** flagged 06-12 are now committed (`2438523`).
- ⚠️ **Carried, still untracked (unchanged from 06-12):** `bash.exe.stackdump`, `FILE_ORGANIZATION_SETUP.md`, backfill `*_progress_*.json`, optimizer scratch (`data/`, `ablation/`, `cache/`, `*_log.txt`, `findings_*.json`, `locked_params_v8_trial180.json`), corpus tooling under `Ross Cameron Day Trading Videos/`, diagnostics (`debug_vwap_jun12.py`, `profile_trial.py`), `research/analysis/outputs/`, `production/data/stream/`, `docs/backtesting_pipeline_discovery.md`. **Recommend one `.gitignore` sweep** — most are regenerable run-state.

## Hygiene flags — custodian pass 2026-06-17 (FLAG ONLY — nothing deleted/moved)
- ✅ **RESOLVED — root-level `.env` files**: `.env`, `.env.paper`, `.env.live`, `.env.example` deleted. Single source of truth is now `production/.env.paper`.
- ⚠️ **Carried (still untracked):** `bash.exe.stackdump`, `FILE_ORGANIZATION_SETUP.md`, `docs/backtesting_pipeline_discovery.md`, `docs/dashboard-ui-plan.md`, backfill `*_progress_*.json`, optimizer scratch, corpus tooling under `Ross Cameron Day Trading Videos/`, `research/analysis/outputs/`, `production/data/stream/`. Recommend `.gitignore` sweep.
- ⚠️ **Legacy monolith component index stale** — Component Index still lists `orchestrator.py`, `patterns.py`, `indicators.py`, `market_temperature.py`, `portfolio_manager.py`, `trading_engine.py`, `scoring_engine.py`, `entry_engine.py`, `exit_engine.py`, `add_on_engine.py`, `live_scanner.py`, `order_manager.py`, `live_broker.py`, `execution.py`, `data_feed.py`, `models.py` as 🟢 active. These belong to the archived monolith (`archive/legacy_monolith/`), NOT the active dual-pipeline. **Recommend: mark all ⚫ deprecated** once confirmed none are imported by `live_scalp_runner.py`/`live_vwap_runner.py` (the active runners use `scalp_engine.py`, `vwap_engine.py`, `broker/alpaca.py` directly).
- ⚠️ **`live_scalp_runner.py` still references `Config.TRADING_MODE` for Tradier guard** — doc comment at top still mentions Tradier as data feed; update to reflect Alpaca as both broker and data feed.
- ℹ️ **NOTE — Alpaca paper has no reset API**: `POST /v2/account` returns 404. Custom balance simulation via `PAPER_STARTING_BALANCE=5000` env var (position-sizing only; actual Alpaca balance stays at $100k). See `research/reset_paper_account.py`.
- ℹ️ **NOTE — record-keeping restructure (this session):** `MEMORY.md` slimmed 411→~62 lines; legacy detail preserved verbatim in `memory/archive_legacy_monolith.md`. New `STATUS.md` (root) + `docs/PARITY.md` are the live "where are we" + parity-ledger sources going forward.
- ⚠️ **6 failing tests in the deprecated monolith path** (`tests/test_indicators.py`, `test_patterns.py`, `test_entry_engine.py`) — NOT imported by the deployed scalp/VWAP strategies, so they don't affect live. **Real finding inside:** `calculate_ema([10,11,12,13,14], period=3)` returns 12.0 at index 3 where a true EMA = 11.5 → `indicators.calculate_ema` is computing a trailing **SMA, not an EMA** (name/behavior mismatch). Also flat_top/ABCD/bull_flag/MACD-negative-gate fixtures fail. NOT skip-marked (would hide the EMA bug) and NOT fixed (deprecated path, changing it needs monolith re-validation). Revisit only if the monolith is revived; otherwise candidates for deletion with the rest of the monolith.
