# Daily Automation Flow — Target State Checklist

Built 2026-07-01 after discovering the dashboard was showing stale state while
real trades filled, and the VWAP + micro-pullback phase silently never launched
that same morning. Every step below is confirmed against actual code (not
memory) as of this date — file:line references included so it can be re-verified
later if the code changes.

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

**⚠️ Found today (Jul 1):** these triggers hit `/trigger`, which is guarded by
`is_session_started_today()` reading `_SESSION_STARTED_FILE` on Render's
ephemeral disk. If a deploy wipes that file mid-session, the NEXT watchdog
trigger will happily start a **second full `run_daily_sessions()`** even
though one already ran partway. This is very likely what happened today —
multiple AM deploys before market open caused 3 scheduler restarts (12:45am,
6:54am, 7:08am ET per Neon `session_logs`), and the session that finally
completed only got through Phase 1 (scalp) before something killed it —
Phase 2 (VWAP + micro-pullback) never logged a start line. **Root cause not
yet fully confirmed — needs the afternoon session's investigation.**

---

## Phase 1 — Main session kickoff (in-Render APScheduler)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 1.1 | 7:00 AM | APScheduler cron fires `run_daily_sessions()` | `production/api/server.py:59-63` |
| 1.2 | immediate | Writes `_SESSION_STARTED_FILE` with today's date (guards against double-fire) | `production/api/session_job.py:76-77` |

**⚠️ Doc drift found:** `session_job.py`'s own module docstring says "APScheduler
daily 8:55 AM ET job" — this is stale, actual registered cron is 7:00 AM ET
(`server.py:63`). Low priority, fix the comment when touching this file.

---

## Phase 2 — Opening Bell Scalp (Strategy #1)

| # | What | Source |
|---|---|---|
| 2.1 | `run_scalp_session(dry_run=False, live=False, start_time='8:00')` runs **synchronously**, blocks Phase 3 until done | `session_job.py:79` |
| 2.2 | Premarket scan → watchlist → entry trigger (first green bar) → exit (target/stop/trailing/time) | `live_scalp_runner.py` |
| 2.3 | Writes `state.json` (candidates, top_pick, completed_trades, pnl) | `session_job.py:99` |
| 2.4 | Appends each completed trade to `trades.json` via `_append_trade()` | `session_job.py:100-101` |

**Verified working today:** 6 round-trip trades filled 9:36-9:47 ET, confirmed
directly against Alpaca `/v2/orders` (not the dashboard — see Phase 5 below for
why that distinction matters).

---

## Phase 3 — VWAP Reclaim (#2) + Micro-Pullback (#3), parallel

| # | What | Source |
|---|---|---|
| 3.1 | Logs `"=== MICRO-PULLBACK & VWAP SESSIONS STARTING (parallel) ==="` | `session_job.py:114` |
| 3.2 | `vwap_thread` runs `run_vwap_session()` (window 10:00-11:30, bar-time enforced) | `session_job.py:117-149` |
| 3.3 | `mp_thread` runs `run_micro_pullback_session()` (window 9:30-11:30) | `session_job.py:151-176` |
| 3.4 | Both threads `.join()`'d — Phase 4 waits for both | `session_job.py:180-183` |
| 3.5 | Each writes its own state file (`vwap_state.json`, `micro_pullback_state.json`) + appends completed trades to `trades.json` | same |

**🔴 BROKEN today — ROOT CAUSE CONFIRMED:** Phase 3 never started because
`run_scalp_session()` (Phase 2) never returned. `execute_trade()`
(`live_scalp_runner.py:611-620`) only exits its monitoring loop when EVERY
armed candidate is marked `done`. A symbol is marked done either by closing a
filled position, or by its own bar counter reaching `config.max_entry_bars`
(10) — but that counter only increments when a bar actually arrives for that
symbol. Checked today's per-candidate bar counts directly in `session_logs`:
**MQ, BACC, and GUACU received ZERO bars the entire session** (vs 6-11 bars
each for the 6 symbols that traded/timed-out normally). With `n` stuck at 0,
the bar-count timeout never fires, `done` never gets set, and the loop blocks
forever — the whole-queue 180s idle-timeout doesn't help either since the
other symbols kept bars flowing normally. This would have hung Phase 3
regardless of whether this morning's deploys/restarts happened at all.
Deploy/restart (Phase 0 note above) was a real, separate issue that killed the
FIRST 7:00 AM attempt, but the SURVIVING 7:08 AM session hung on this bug with
zero further restarts. **Fix:** add a wall-clock fallback to the per-symbol
entry timeout, independent of bar count. [[deploy_during_cron_incident]]

**🟢 FIXED Jul 1 (`2a6bdba`, standing gap, not today's bug):** micro-pullback
had ONLY ever completed one entry attempt, ever (Jun 30, SVRE) — it died to a
12-second limit-fill timeout with no market-order fallback (scalp and VWAP
both got that fallback in earlier fixes; micro-pullback never did). Ported the
same retry pattern in. Verified: 19/19 `test_micro_pullback_engine.py` pass,
parity audit clean. **Untested against a real live fill** — needs a genuine
entry attempt to confirm end-to-end. [[micro_pullback_entry_retry_todo]]

---

## Phase 4 — Persist to Neon (durable storage)

| # | What | Source |
|---|---|---|
| 4.1 | Logs `"=== PERSISTING SESSION TO DB ==="` | `session_job.py:186` |
| 4.2 | Calls `persist_session(scalp_state_data, vwap_state_data)` | `session_job.py:189` |

**⚠️ UNVERIFIED, needs afternoon check:**
- `persist_session()` only takes scalp + VWAP state — **micro-pullback trades
  are never passed to it**. The code comment claims "micro-pullback trades are
  appended via `_append_trade` above, so no additional call needed" — but
  `_append_trade()` only writes to the **ephemeral** `trades.json` file, not to
  Neon. If that comment is wrong, micro-pullback trades may **never reach
  durable storage** at all, even on a day it does trade. Needs a direct check
  of `session_persistence.py` to confirm what tables it actually writes and
  whether micro-pullback data has any path into Neon.
- Neon `session_runs` table was found **completely empty** today despite
  `persist_session` apparently being called every day since Phase 12/13 shipped.
  Either it's silently failing, or it writes to a different table than expected
  (`live_trades` has real rows, so *something* works — but `session_runs`
  specifically does not). **Partially explained (Jul 1 14:00 ET):** today
  specifically, `persist_session()` never ran at all because `run_daily_sessions()`
  was still stuck in the Phase 2 bar-starvation hang (now fixed, `5a1f0e0`) when
  a later redeploy ended the process — so zero rows today isn't surprising. Still
  needs re-checking on a normal (non-stuck) day to see if `session_runs` populates
  correctly once Phase 2/3/4 all complete normally. [[session_capture_pipeline_fix]]

---

## Phase 5 — Dashboard API (serves the frontend, runs continuously)

| # | Endpoint | Reads from | Status |
|---|---|---|---|
| 5.1 | `GET /dashboard` | `state.json` + `vwap_state.json` (merged) | 🟢 **FIXED Jul 1** (`322b148`) — all 3 runners now call a new `_write_live_state()` right after every entry/exit, not just once when the whole session function returns. Smoke-tested directly (no broker): `_infer_stage()` correctly reads ENTERED/EXITED from the new incremental writes. **Not yet confirmed on a real live day** (built after market close) — watch tomorrow. |
| 5.2 | `GET /trades` | Neon `live_trades` (was `/tmp/jtrader/trades.json`) | 🟢 **FIXED Jul 1** (`8877566` backend + `ae533f2` frontend) — reads durable `live_trades` instead of the ephemeral file, with a fallback to the old file if the DB is unreachable. Verified against the live deployed API (13 real trades, correctly shaped) and a live browser render of the updated Trade History table. |
| 5.3 | Micro-pullback section in `/dashboard` response | `micro_pullback_state.json` | 🟢 **FIXED Jul 1** (`9412848` backend + `f8a6bca` frontend) — `dashboard.py` now has a `"micro_pullback"` key mirroring scalp/vwap's shape; `jtrader-dashboard` has a matching collapsible section. Verified end-to-end (tsc clean, build succeeds, live render confirmed both empty-state and mock-populated paths). Awaiting a real live trade to confirm stage inference against actual (not synthetic) data. |

**Note:** `/dashboard` (5.1) is fixed but not yet confirmed against a real
trading day. Until tomorrow's session confirms it, cross-check against
Alpaca `/v2/orders` + `/v2/positions` directly if anything looks off.
`/trades` (5.2) is confirmed working against real historical + today's data.

---

## Phase 6 — Post-session capture (GitHub Actions, off-Render)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 6.1 | 10:00 AM | "Early capture" — wakes Render, pulls `/dashboard`, `/bars_dump`, `/news_dump`, `/trades`, `/logs`, generates journal via `generate_journal.py`, pushes all to `data` branch | `.github/workflows/session-capture.yml` (cron `0 14 * * 1-5`) |
| 6.2 | 12:00 PM | "Full capture" — same steps again, intended to run after both strategies are done (~11:45 ET) | same (cron `0 16 * * 1-5`) |

**🔴 Consequence of Phase 5's bugs:** this automated capture is pulling
`/dashboard` and `/trades` — both confirmed broken — **twice a day, into
permanent git history on the `data` branch.** Every day until Phase 5 is
fixed, the archived record for that day understates or omits real trades.
This makes the capture pipeline itself untrustworthy as a historical record
right now, not just the live view.

**🟢 SEPARATE BUG FIXED Jul 1 (`147372a`):** the workflow had a 100% failure
rate since Jun 22 — `generate_journal.py` crashed on a dict/list wrapper
mismatch (`_trades.json` is `{"trades": [...]}`, not a bare list), and the
crash happened *after* the Render pull succeeded but *before* the push-to-
`data`-branch step, so real data was fetched every day and silently thrown
away for ~2 weeks. Fixed and verified via manual `workflow_dispatch` — first
successful capture since Jun 19 landed as `data: session capture + journal
2026-07-01` (`19ca97c`). This is now fixed at the capture-mechanics level;
the Phase 5 data-quality issue above (capturing broken/stale fields) is
still open and separate. [[session_capture_pipeline_fix]]

---

## Phase 7 — Rel-vol baseline refresh (prepares TOMORROW, not today)

| # | Time (ET) | What | Source |
|---|---|---|---|
| 7.1 | 4:30 PM | `build_baseline_cloud.py` computes next day's 30-day avg-volume baseline per symbol + weekly yfinance float refresh (stale >7 days) → upserts Neon `rel_vol_baselines` + `active_symbols` | `.github/workflows/rel-vol-baseline.yml` (cron `30 20 * * 1-5`) |

Not yet re-verified against today's specific run; presumed working based on
recent history (no incidents reported since HybridRelVol shipped Jun 30).

---

## Phase 8 — Manual / human-triggered (NOT on any cron)

These are documented operating-rule steps, run by the user or an agent, not
automated. Listed here because they're part of the intended daily flow even
though nothing schedules them yet.

| # | What | When | Source |
|---|---|---|---|
| 8.1 | `pull_live_bars.py` — pull `/bars_dump` into TimescaleDB `stock_candles_live_1m` | before any deploy | `production/data/live_capture/pull_live_bars.py` |
| 8.2 | `session_report.py` — paper vs live-counterfactual P&L report | before any deploy | `production/data/live_capture/session_report.py` |
| 8.3 | `daily_validation.py` — rebuild session via Alpaca backfill + re-sim, prove sim ≈ live | ad hoc, not daily | `production/data/live_capture/daily_validation.py` |

**Open question to raise with user:** should 8.1/8.2 be automated into a cron
(e.g., piggybacking on the 12:00 PM capture workflow) instead of relying on a
human remembering to run them before every deploy? Given today's finding that
`/dashboard` and `/trades` can't be trusted, `pull_live_bars.py` +
`session_report.py` against Neon `session_logs` directly may currently be the
*most* reliable source of daily truth — worth prioritizing its automation.

---

## Audit 2026-07-02 (end of day) — full pass against code + Neon + Alpaca

### 🔴 NEW P0 — Phase 0 double-fire CONFIRMED LIVE, with real (paper) trades

`server.py:78-83`: on ANY server start between 7:00-11:59 ET, if
`_SESSION_STARTED_FILE` is missing (every deploy wipes it — ephemeral disk),
the server auto-triggers a **full new `run_daily_sessions()`**. Today a
~11:55 ET push (the bug-fix deploy) restarted Render inside that window →
a SECOND scalp session launched at 11:59 ET and traded **7 more positions
(PLBL, USDE, CWD, SDEV, WHLR, PPCB, CLRO), 11:59-12:07 ET** — midday chop,
outside the strategy's 9:30-9:40 design window, and past the 11:45 no-deploy
cutoff. All rows visible in Neon `live_trades` (decision_time 15:59-16:07 UTC)
and Alpaca. Yesterday's version of this was "suspected"; today it's proven.
The "never push 08:00-11:45 ET" rule is insufficient — the danger window is
**any deploy before 12:00 ET**. Interim rule until fixed: **no pushes to main
before 12:00 ET, period.** Real fix = the started-flag must live in Neon, not
on ephemeral disk (option 2 in `docs/SESSION_RESILIENCE_DESIGN.md`, currently
deferred — recommend un-deferring this one piece).

### Same-day fixes shipped (all reset their steps' verification counters)

| Commit | What |
|---|---|
| `ccae5d1` | Alpaca prior-close retry (3x w/ backoff) — a single 500 at the 9:45 re-scan had zeroed BOTH VWAP and MP watchlists today; persistence "can't adapt type 'dict'" (top_pick dict) — first session's persist rolled back entirely; dashboard scalp trade_count (was capped at 1 via entry_price) |
| `0c5ddce` | MP runner migrated to HybridRelVol (was still on dead 5-day TradierRelVol) |
| `31397d5` | Scalp entries: marketable limit +0.25% (12/15 exact-close limits missed today — adverse selection confirmed live) |
| `7bd92d5` | Marketable-limit fill model in all 3 sims (docs/SIM_FILL_MODEL_DESIGN.md) |
| `2a11234` | VWAP live config → fill-aware Trial 184 (sealed 2025: +$1,844, PF 1.60); live limit = signal +0.97%; market-fallback cap = tuned headroom (was flat 2%); MP fallback cap 2%→0.5% |

### Status of the Jul 1 open items (re-verified today)

1. Phase 3 bar-starvation hang → **wall-clock fallback WORKED today**:
   CNNE/BACCR/LOCO all logged "No entry after 10min wall-clock — marking done
   (bar starvation)". Day 1/3 ✅.
2. `/dashboard` state sync (5.1) → incremental writes worked (stages updated
   live) but the header showed **0 trades while 2 were filled** — that was the
   trade_count bug, fixed `ccae5d1`, unverified live. Still 0/3.
3. `/trades` → Neon (5.2) → working; `live_trades` has today's rows. BUT see
   new parser-attribution issue below. Day 1 ⚠️.
4. MP dashboard section (5.3) → rendered correctly (IDLE) — no MP trade yet to
   confirm stage inference. Still awaiting a real fill.
5. MP trades → Neon (Phase 4) → **CONFIRMED GAP**: `session_runs` today has
   scalp + vwap rows only; `persist_session()` still never receives MP state.
   Open.
6. `session_runs` empty mystery → **RESOLVED**: populates fine once a session
   completes AND the dict bug is fixed — today's 2 rows came from the (buggy,
   unwanted) second session, which ran AFTER the `ccae5d1` fix deployed. Note
   the upsert on (run_date, strategy) means the second session **overwrote the
   first session's real results** — scalp row shows the midday CLRO session
   (pnl -$47.99), not the real 9:30 session (-$102.38). Double-fire corrupts
   history, not just adds trades.
7. MP market-fallback retry → still untested live (MP had no watchlist today
   thanks to the Alpaca 500). Cap since tightened to 0.5%.
8. Bar poller log wording → ✅ DONE Jul 2 `a6f5889` (verified in today's logs).
9. `session_job.py` stale docstring → ✅ DONE (now says 7:00 AM ET).
10. Capture mechanics → session-capture.yml ran; ALSO NEW: `session-report.yml`
    (`a9c2e3e`, 12:15 PM ET cron) had its **first scheduled run today** — it's
    what populated `live_trades` rows 44-52 at 18:01 UTC. Working, but…

### 🟠 NEW — session-report parser attribution bugs in `live_trades`

Today's rows show cross-symbol contamination: PLBL's row carries exit_reason
"FIRST_GREEN bar on CLRO", USDE's second row says "FIRST_GREEN bar on SDEV",
WHLR has exit_reason NULL, and paper_pnl signs don't reconcile against the
runner's own DAILY SUMMARY (-$102.38 for the real session). The parser handles
the multi-candidate interleaved log format imperfectly — plausible-looking but
wrong rows are worse than missing rows for a journal. Needs a parser pass with
the multi-position log format + a reconciliation check against Alpaca fills.

### Phases not yet re-verified (unchanged from Jul 1 status)

- Phase 7 rel-vol baseline: now has TWO workflows — original + cloud builder
  (`a25f52d`, no-DB variant). Doc predates the second; fold in next audit.
- Phase 8 manual scripts: `pull_live_bars.py` run manually today pre-deploy
  (83 bars, 285 news) — the "before any deploy" discipline held.

---

## Verification Tracker

For each step, track the last 3 trading days it was checked. All three must
be ✅ with **no code changes to that step's files** in between, or the streak
resets to 0.

| Step | Day 1 | Day 2 | Day 3 | Status |
|---|---|---|---|---|
| 0.1-0.5 Watchdog triggers | 2026-07-02 🔴 | | | 0/3 — double-fire CONFIRMED live (second session 11:59 ET after deploy); startup auto-trigger is the mechanism, not the watchdog crons themselves |
| 1.1-1.2 Session kickoff | 2026-07-02 ✅ | | | 1/3 (7:00 ET fire clean) |
| 2.1-2.4 Scalp | 2026-07-01 ✅ / 07-02 ✅* | | | reset — entry logic changed `31397d5` (marketable limit); *session itself ran clean |
| 3.1-3.5 VWAP + Micro-Pullback parallel | 2026-07-02 🔴 | | | 0/3 — launched fine (hang fix verified ✅) but both watchlists zeroed by Alpaca 500 (retry shipped `ccae5d1`, unverified) |
| 4.1-4.2 Neon persistence | 2026-07-02 ⚠️ | | | dict bug fixed + `session_runs` now populates, but MP still has no path in, and double-fire OVERWRITES same-day rows |
| 5.1-5.2 Dashboard/trades sync | 2026-07-02 ⚠️ | | | stages live-updated ✅; trade_count showed 0 (fixed `ccae5d1`, unverified); /trades works but parser attribution bugs |
| 5.3 Micro-pullback dashboard section | 2026-07-02 ✅ (empty-state) | | | still awaiting a real MP trade |
| 6.1-6.2 GitHub capture | 2026-07-02 🟢 | | | 2/3 mechanics |
| 6.3 session-report.yml (12:15 ET, NEW `a9c2e3e`) | 2026-07-02 ⚠️ | | | ran + wrote live_trades, but attribution bugs in output |
| 7.1 Rel-vol baseline refresh | | | | not started (now 2 workflows — doc update pending) |
| 8.1-8.3 Manual post-session scripts | 2026-07-02 ✅ (8.1) | | | pull-before-deploy discipline held |

---

## Open items after the 2026-07-02 audit (supersedes the Jul 1 list below)

1. **P0 — kill the double-fire**: move `_SESSION_STARTED_FILE` to a Neon flag
   (SESSION_RESILIENCE_DESIGN.md option 2, un-defer just this piece). Until
   then: NO pushes to main before 12:00 ET. Also consider: second-session
   upsert overwrote the real session's `session_runs` row — flag should also
   prevent that.
2. **session-report parser attribution** — cross-symbol exit_reason
   contamination + P&L mismatch vs runner summary in `live_trades`; add
   reconciliation against Alpaca fills.
3. **MP state → `persist_session()`** — micro-pullback still has no path into
   `session_runs`.
4. Verify tomorrow (all shipped today, zero live evidence yet): prior-close
   retry, dashboard trade_count, scalp +0.25% limit fill-rate, VWAP Trial 184
   + 0.97% headroom entries, MP HybridRelVol + 0.5% cap.
5. Fold the second rel-vol workflow (`a25f52d` cloud builder) into Phase 7.
6. Scalp cross-strategy position claim (`_positions_lock`) — task #27, still open.

## Open items from Jul 1 needing resolution before their step can pass

1. ✅ **DONE** — Root-cause the Phase 3 (VWAP + MP) no-launch. Primary cause
   (bar-starved symbols hanging the scalp loop) fixed `5a1f0e0`. Secondary
   deploy/restart cause still open (lower priority). [[deploy_during_cron_incident]]
2. Fix `/dashboard` state sync (Phase 5.1) — completed trades not reflected
   in `state.json` mid-session. **Still open.** [[repo_dashboard_sync_rule]]
3. Fix `/trades` to read Neon `live_trades`, not the ephemeral file (Phase 5.2).
   **Still open.**
4. ✅ **DONE** — Add micro-pullback to `/dashboard` (Phase 5.3), both backend
   (`9412848`) and frontend (`f8a6bca`). Awaiting a real trade to confirm
   stage inference against actual (not synthetic) data.
5. Confirm whether micro-pullback trades ever reach Neon at all (Phase 4).
   **Still open.**
6. Confirm why `session_runs` table is empty despite `persist_session` running
   (Phase 4). **Partially explained** — today specifically never reached
   Phase 4 due to the Phase 3 hang; re-check on a normal day.
7. ✅ **DONE** — Fix micro-pullback's missing market-fallback-on-missed-limit
   retry (Phase 3), `2a6bdba`. Untested against a real live fill yet.
   [[micro_pullback_entry_retry_todo]]
8. Fix `TradierBarPoller` log wording (cosmetic, any time). **Still open.**
   [[bar_poller_log_wording_todo]]
9. Fix stale docstring in `session_job.py` (says 8:55 AM, actual is 7:00 AM).
   **Still open.**
10. ✅ **DONE** — Fixed `session-capture.yml`'s 100% failure rate since Jun 22
    (`147372a`) — was silently discarding real pulled data every run.
    [[session_capture_pipeline_fix]]
