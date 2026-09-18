# Daily Automation Flow — Target State Checklist

Built 2026-07-01, last updated **2026-07-10** (folded in Jul 2-10 fixes).

**How to use this doc:** work through it top to bottom. For each step, confirm
it still matches the code, then track it in the Verification Tracker at the
bottom. A step is only "trusted" once it works correctly **3 consecutive
trading days with zero code changes to that step in between**. A code change
resets its counter to 0.

---

## Phase 0 — Wake-up / safety net (before the real session)

| # | Time (ET) | What | Trigger | Source |
|---|---|---|---|---|
| 0.1 | 6:50 AM | GitHub Action pings Render `/trigger`, wakes free-tier instance from sleep | cron `50 10 * * 1-5` | `.github/workflows/runner-watchdog.yml` |
| 0.2 | 7:25 AM | Same, backup in case GitHub Actions queue delayed the 6:50 run | cron `25 11 * * 1-5` | same |
| 0.3 | 8:00 AM | Same, safety net during premarket scan window | cron `0 12 * * 1-5` | same |
| 0.4 | 9:05 AM | Same, explicitly labeled "post-deploy recovery — re-triggers if deploy wiped runner" | cron `5 13 * * 1-5` | same |
| 0.5 | 9:10 AM | Same, final safety net before the 9:25 refresh window | cron `10 13 * * 1-5` | same |

**✅ Double-fire FIXED `811b7c7`:** session-started flag moved from ephemeral
`_SESSION_STARTED_FILE` to **Neon `session_flags` table** with atomic claim
(INSERT ... ON CONFLICT). Deploy no longer wipes the guard. Rule remains:
**no pushes to main before 12:00 ET** until 3 clean days confirmed.

---

## Phase 1 — Main session kickoff (in-Render APScheduler)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 1.1 | 7:00 AM | APScheduler cron fires `run_daily_sessions()` | `production/api/server.py:59-63` |
| 1.2 | immediate | Claims today's date in Neon `session_flags` (atomic, prevents double-fire) | `production/api/session_job.py` |
| 1.3 | immediate | Holiday guard: checks Tradier market calendar, skips if market closed | `production/api/session_job.py` (`206b2ea`) |

---

## Phase 2 — Opening Bell Scalp (Strategy #1)

| # | What | Source |
|---|---|---|
| 2.1 | `run_scalp_session(dry_run=False, live=False, start_time='8:00')` runs **synchronously**, blocks Phase 3 until done | `session_job.py` |
| 2.2 | Premarket scan → watchlist → entry trigger (market_open / first_green) → exit (target/stop/trailing/time) | `live_scalp_runner.py` |
| 2.3 | Trial 211 config: `market_open` entry, `max_entry_bars=5`, `require_news=False` (issue #14) | `live_scalp_runner.py:60-80` |
| 2.4 | Marketable-limit entry: signal price + 0.25% headroom (`31397d5`) | same |
| 2.5 | Wall-clock fallback: marks bar-starved symbols done after timeout (`5a1f0e0`) | `live_scalp_runner.py:651-664` |
| 2.6 | Writes `state.json` (candidates, top_pick, completed_trades, pnl) + appends to `trades.json` | `session_job.py` |

**Known issue:** `bars_since_open` off-by-one fixed `f99771b` Jul 9. Validating
(3 clean days from next armed candidate that fills). See PARITY.md #4.

---

## Phase 3 — VWAP Reclaim (#2) + Micro-Pullback (#3), parallel

| # | What | Source |
|---|---|---|
| 3.1 | Logs `"=== MICRO-PULLBACK & VWAP SESSIONS STARTING (parallel) ==="` | `session_job.py` |
| 3.2 | **VWAP: SUSPENDED** (`VWAP_SUSPENDED=True`, `c766488`) — issue #14 proved edge was lookahead bias. Early return logs warning + writes minimal state. | `session_job.py` |
| 3.3 | `mp_thread` runs `run_micro_pullback_session()` (window 9:30-11:30) | `session_job.py` |
| 3.4 | Both threads `.join()`'d — Phase 4 waits for both | `session_job.py` |

**MP status:** UNDER-REVIEW (fill model re-opt failed sealed). Market-fallback
retry shipped (`2a6bdba`), cap tightened to 0.5%. HybridRelVol ported (`0c5ddce`).
Still awaiting first real live fill.

---

## Phase 4 — Persist to Neon (durable storage)

| # | What | Source |
|---|---|---|
| 4.1 | Logs `"=== PERSISTING SESSION TO DB ==="` | `session_job.py` |
| 4.2 | `persist_session(scalp_state_data, vwap_state_data)` → Neon `session_runs` + `live_trades` | `session_job.py` |
| 4.3 | MP state added to persist call (`33`) | `session_job.py` |

**✅ `session_runs` empty mystery RESOLVED** — populates correctly once a session
completes normally (confirmed Jul 2+). Double-fire upsert overwrite also fixed
by the Neon session_flags guard (`811b7c7`).

---

## Phase 5 — Dashboard API (serves the frontend, runs continuously)

| # | Endpoint | Status |
|---|---|---|
| 5.1 | `GET /dashboard` — reads state files, merges, serves frontend | ✅ Incremental state writes working (`322b148`). Trade count fix `ccae5d1`. |
| 5.2 | `GET /trades` — reads Neon `live_trades` | ✅ Working (`8877566` backend + `ae533f2` frontend). Parser attribution fixed (`session_report_parser_rewrite`). |
| 5.3 | Micro-pullback section in `/dashboard` | ✅ Renders (`9412848` + `f8a6bca`). Awaiting real MP trade. |

---

## Phase 6 — Post-session capture (GitHub Actions, off-Render)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 6.1 | 10:00 AM | "Early capture" — pulls dashboard/bars/news/trades/logs, generates journal, pushes to `data` branch | `.github/workflows/session-capture.yml` |
| 6.2 | 12:00 PM | "Full capture" — same steps, after both strategies done | same |
| 6.3 | 12:15 PM | Session report — parses logs → `live_trades` in Neon | `.github/workflows/session-report.yml` (`a9c2e3e`) |
| 6.4 | 1:00 PM | Session capture to TimescaleDB — auto-persists session data | `.github/workflows/session-capture-db.yml` (`07f767c`) |

**✅ Capture mechanics fixed `147372a`** — dict/list wrapper bug was silently
discarding data since Jun 22. Working since Jul 1.

---

## Phase 7 — Rel-vol baseline refresh (prepares TOMORROW, not today)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 7.1 | 4:30 PM | `build_baseline_cloud.py` — 30-day avg-volume baseline per symbol + weekly yfinance float refresh → Neon `rel_vol_baselines` + `active_symbols` | `.github/workflows/rel-vol-baseline.yml` (`a25f52d`) |

Cloud-only variant (no local DB required). Runs as GitHub Action.

---

## Phase 8 — Manual / human-triggered (NOT on any cron)

| # | What | When | Source |
|---|---|---|---|
| 8.1 | `pull_live_bars.py` — pull `/bars_dump` into TimescaleDB | before any deploy | `production/data/live_capture/pull_live_bars.py` |
| 8.2 | `session_report.py` — paper vs live-counterfactual P&L report | before any deploy | `production/data/live_capture/session_report.py` |
| 8.3 | `daily_validation.py` — rebuild session via Alpaca backfill + re-sim | ad hoc | `production/data/live_capture/daily_validation.py` |

**Note:** 8.1/8.2 discipline: run before any deploy (deploys wipe ephemeral
capture + logs on Render). Session-report GH Action (`a9c2e3e`) + session-capture-db
(`07f767c`) now handle most of this automatically — manual runs are backup only.

---

## Verification Tracker

| Step | Status | Notes |
|---|---|---|
| 0.1-0.5 Watchdog triggers | ✅ Fixed (`811b7c7`) | Neon session_flags atomic claim. No-push-before-12:00-ET rule still active. |
| 1.1-1.3 Session kickoff + holiday guard | ✅ Working | Holiday guard `206b2ea`. |
| 2.1-2.6 Scalp | 🟡 Validating | off-by-one fix `f99771b` Jul 9, need 3 clean days. `require_news=False` `c766488` Jul 10. |
| 3.1-3.4 VWAP + MP parallel | 🔴 VWAP suspended | VWAP: `VWAP_SUSPENDED=True` (issue #14). MP: UNDER-REVIEW. |
| 4.1-4.3 Neon persistence | ✅ Working | MP state added. Double-fire guard prevents overwrites. |
| 5.1-5.3 Dashboard/trades sync | ✅ Working | All endpoints functional. Parser attribution fixed. |
| 6.1-6.4 GitHub capture | ✅ Working | 4 workflows, all functional since Jul 1-2 fixes. |
| 7.1 Rel-vol baseline | ✅ Working | Cloud-only variant `a25f52d`. |
| 8.1-8.3 Manual scripts | ✅ Backup only | Automated equivalents now handle most daily capture. |

---

## Resolved items (from Jul 1-2 audits)

All items from the original Jul 1 and Jul 2 open-items lists are now resolved:

1. ✅ Phase 3 bar-starvation hang → wall-clock fallback `5a1f0e0`
2. ✅ `/dashboard` state sync → incremental writes `322b148` + trade_count `ccae5d1`
3. ✅ `/trades` → Neon `live_trades` `8877566`
4. ✅ MP dashboard section → `9412848` + `f8a6bca`
5. ✅ MP state → persist_session → added
6. ✅ `session_runs` empty → populates correctly
7. ✅ MP market-fallback retry → `2a6bdba` (awaiting first real fill)
8. ✅ Bar poller log wording → `a6f5889`
9. ✅ Stale docstring → `3104028`
10. ✅ Session capture 100% failure → `147372a`
11. ✅ Double-fire → Neon session_flags `811b7c7`
12. ✅ Parser attribution → rewrite (session_report_parser_rewrite)
