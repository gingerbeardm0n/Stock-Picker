# Project History & Component Ledger — jTrader

Living record of what was built, when, why — plus a component index and file-hygiene flags.
Maintained by the **historian** skill (`.claude/skills/historian`). Bootstrap pass written manually
2026-05-31 from git history + session context; incremental passes append from `git log`.

**History watermark (last commit folded in):** `8dfc583` (2026-05-31)

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

### Phase 5 — Orchestrator migration + parity (2026-05-30 → 05-31)
- `c2fa532` 05-30 — **migrate per-minute decision logic into the shared `Orchestrator`** (sim/live one engine);
  H0 fix (sim MACD was dead: BAR_HISTORY_SIZE 30→40 + wrong key). golden-day regression byte-identical.
- `5711b05` 05-30 — **parity harness** (parity_check.py): proved sim == live on all 5 golden days. Fixed 3
  live bugs it surfaced: add-on 3× cap, `t1_hit` never set, M1/H1 add-on P&L accounting.
- `b0f8c66` 05-30 — **wire live_scanner to the Orchestrator** (flag-gated `_use_orchestrator`, default OFF).
- `8dfc583` 05-31 — batching unit test; logged the intraday high-day-momo scanner gap. **Merged to main.**

---

## Component Index
Status: 🟢 active · 🟡 partial/transitional · ⚫ deprecated (safe to remove)

### The engine (`production/trading/` — ONE copy, sim + live share it)
| File | Purpose | Status | Since |
|---|---|---|---|
| `orchestrator.py` | The one per-minute decision pipeline (`on_minute`). Broker-agnostic. | 🟢 | c2fa532 |
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
| `live_scanner.py` | live runtime: watchlist discovery + (flag-gated) orchestrator path | 🟡 flip default-OFF | b0f8c66 |
| `broker/base.py`,`broker/tradier.py` | broker/data-feed interfaces + Tradier impl | 🟢 | cf1a431 |

### Simulator (`production/simulator/` — adapters only, ZERO logic)
| `simulation_engine.py` | data loader + minute loop → `orch.on_minute`; SimBroker | 🟢 (+⚫ dead methods inside) |
| `sim_broker.py` | SimBroker (Broker over PositionManager) | 🟢 | c2fa532 |

### Research tooling (`research/optimizer/`, `research/maintenance/`, `research/analysis/`)
| `optimizer/simulate_one.py` | run a date range → metrics (objective=`consistency`) | 🟢 |
| `optimizer/optuna_run.py` | the optimizer | 🟢 |
| `optimizer/objective_functions.py` | selectable objective formulas (+tests) | 🟢 |
| `optimizer/golden_baseline.py` | sim regression oracle (5 golden days) | 🟢 |
| `optimizer/parity_check.py` | sim==live decision-parity harness | 🟢 |
| `optimizer/validate_findings.py` | one-off finding backtests | 🟢 |
| `optimizer/oracle_*.py`, `run_oracle_*.py` | value-of-perfect-info temperature test (UNRUN) | 🟡 needs 2021-24 universe |
| `maintenance/backfill_rel_vol_historical.py` | rel_vol backfill (done 2021-25) | 🟢 one-shot |
| `maintenance/compress_and_cleanup.py` | DB compress/cleanup (done) | 🟢 one-shot |
| `analysis/scripts/validate_market_temperature.py` | emits hot/neutral/cold day labels | 🟢 |

---

## Deprecations (dead — safe to delete, kept for traceability)
- ⚫ `simulation_engine._process_minute` + `_scan_for_entry` — logic moved to `orchestrator.on_minute`;
  sim now delegates. The methods are unreferenced. **Safe to delete** (golden-check after).
- ⚫ `simulation_engine._cushion_size_multiplier` — moved to `sizing.cushion_size_multiplier`.
- 🟡 `live_scanner._collect_entry_candidate` / `_execute_pending_entry` / `_try_exit` — become dead once
  `_use_orchestrator` defaults True; still the live path today. Remove after the flip is verified live.

---

## Hygiene flags (for user review — NEVER auto-deleted)
- **Root-level `.py` (violate file-org rule "none except config.py"):** `production/cancel_stop_and_sell.py`,
  `compare_entry_logic.py`, `compare_signals.py`, `connect_alpaca.py`, `diagnostic_march6.py`,
  `manual_sell_breakeven.py`. → move to `research/maintenance/diagnostics/` or `archive/`.
- **Untracked binaries/data that should be `.gitignore`'d:** `research/optimizer/*.db` (optuna/results),
  `*.parquet` cache, `*.log`/`*.log.err`, `research/optimizer/data/gapper_universe.csv` (2.8 MB),
  `production/services/stocks_in_price_range.{json,txt}`, backfill `*_progress.json`, `temp_0295.txt`.
- **Stale-ish docs to reconcile:** `LIVE_SIM_PARITY_SPEC.md` (migration now mostly done — mark complete),
  `PROJECT_STATUS_AND_PLAN.md` (overlaps AUTONOMOUS_QUEUE; consider merging), `FILE_ORGANIZATION_SETUP.md`
  (untracked root — clarify or place).
- **Worktrees/branches:** 8 `claude/*` worktree branches all at/behind main → prune stale ones.
- **Concept pages dated 2026-05-21** but reflect newer code in places (e.g. front_side_back_side describes a
  pre-fix MACD state) — refresh against current engine.
