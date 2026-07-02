# Overnight Work Plan — 2026-07-01 → 07-02

Execution plan for an autonomous Sonnet agent. Written by the evening session that
shipped today's 8 fixes. Every task is self-contained: context, exact files, steps,
verification, and abort criteria. **Read the HARD RULES first. They override
everything else in this document.**

---

## HARD RULES (violating any of these = stop and leave a note instead)

1. **PUSH CUTOFF: no `git push` to Stock-Picker `main` after 06:00 AM ET.**
   Every push triggers a Render redeploy. The daily trading session cron fires at
   7:00 AM ET, with watchdog triggers starting 6:50 AM ET. A deploy landing near
   those kills the session process mid-flight (this exact thing happened the morning
   of Jul 1 — see `memory/deploy_during_cron_incident.md`). After 06:00 ET you may
   still commit locally; just don't push. Leave unpushed commits with a note.
2. **NEVER launch parallel/bulk agents.** Work strictly sequentially, one task at a
   time, in the order listed.
3. **NEVER edit simulator/engine logic** (`production/simulator/*`,
   `scalp_engine.py`, `vwap_engine.py`, `micro_pullback_engine.py`,
   `*_models.py` config values). Anything touching trade behavior needs backtest
   validation the user must approve. Log wording and comments are fine.
4. **Every commit to Stock-Picker runs a pre-commit parity audit.** Expected result:
   `25 checks, 23 passed, 2 failed` — the 2 known failures are
   `scalp sim uses rank_candidates()` and `VWAP sim checks max_float`.
   **Any third failure = regression. Revert your change, do not commit.**
5. **Verify before commit, every time**: `py_compile` for any touched Python file,
   plus the relevant test suite:
   `cd production && python -m pytest tests/test_scalp_engine.py tests/test_vwap_engine.py tests/test_micro_pullback_engine.py -q`
   (77 tests, all must pass).
6. **Never place, modify, or cancel any order** on any broker API, paper or live.
   Read-only API access (GET orders/positions/quotes/timesales) is fine.
7. **Secrets**: env values come from `production/.env.render.dec` (already decrypted
   locally). Never print full secret values into logs, commits, or docs. Never
   commit `.env.render.dec`. If it's missing, run
   `bash production/scripts/decrypt-local.sh`.
8. Commit messages: conventional-commit style matching today's history (see
   `git log --oneline -10`). End body with
   `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` (adjust model name to
   whoever executes).
9. If a task fails twice, **skip it**, append what happened to the Progress Log at
   the bottom of this file, and move on. Do not rabbit-hole.
10. Checkpoint after EVERY task: update the Progress Log section at the bottom of
    this file (status, commit hash, notes). This file is the handoff artifact.

## Working directories

- **Stock-Picker main checkout**: `C:\Repositories\Stock-Picker` (branch `main`) —
  do all Stock-Picker work here.
- **Worktree** `C:\Repositories\Stock-Picker\.claude\worktrees\elated-euclid-5e0d46`
  (branch `claude/elated-euclid-5e0d46`) — contains uncommitted work to harvest in
  Task A4. Do not do new work there.
- **Dashboard frontend**: `C:\Repositories\jtrader-dashboard` (branch `master`).

---

## PHASE A — Safe quick wins (do first, all pushable)

### A1. Bar poller log reword
**Why**: `TradierBarPoller: pushed 5/7 bars at 09:26:05 (live)` reads like a failure;
5/7 is normal (dedup / no fresh bar). User asked for clearer wording.
Memory: `memory/bar_poller_log_wording_todo.md`.
**File**: `production/trading/broker/tradier.py`, the `logger.info` at the end of
`TradierBarPoller._poll_all` (~line 550).
**Change** the f-string to produce:
`TradierBarPoller: 5 new bar(s) pushed (7 watched, 2 no-op) at 09:26:05 (live)`
i.e. `f"TradierBarPoller: {pushed} new bar(s) pushed ({len(symbols)} watched, {len(symbols) - pushed} no-op) at {now_et.strftime('%H:%M:%S')} ({'delayed' if self._delay_min else 'live'})"`
**Verify**: py_compile. Logging-only, no test changes needed.
**Commit**: `fix(logs): clarify TradierBarPoller per-poll summary wording`

### A2. Stale docstring + stale frontend text
**Why**: session start moved 8:55→7:00 AM ET long ago; two leftovers confuse readers.
1. `production/api/session_job.py` module docstring says
   "APScheduler daily 8:55 AM ET job" — actual cron is 7:00 AM ET
   (`production/api/server.py:63`). Fix the docstring.
2. `C:\Repositories\jtrader-dashboard\src\components\TradeHistory.tsx` empty-state
   text says "first session runs tomorrow at 8:55 AM ET" — change to
   "No trades yet — sessions run Mon–Fri from 7:00 AM ET".
**Verify**: py_compile for (1); `npx tsc --noEmit` + `npm run build` in the
dashboard repo for (2).
**Commits**: one per repo. Push dashboard repo (`master`) freely — Vercel deploys
don't touch the trading runner.

### A3. Fix line-ending noise in main checkout
**Why**: `git status` on main shows `M production/api/session_persistence.py`,
`M production/tests/test_micro_pullback_engine.py`, `M production/tests/test_vwap_engine.py`
— artifacts of today's `git show main:x > x` syncs (LF→CRLF). Not real changes.
**Steps**: confirm each diff is whitespace/line-endings only
(`git diff --ignore-all-space --stat <file>` → empty), then
`git checkout -- <file>` each. Also `git checkout -- .env.example` if its deletion
is unstaged noise — BUT check first: if `.env.example` was deliberately deleted
(root env cleanup Jun 17), `git rm .env.example` + include in the A4 commit instead.
**Verify**: `git status` clean of those entries. Nothing to push by itself.

### A4. Harvest worktree: hygiene sweep + docs → main
**Why**: The Jul 1 morning session did repo hygiene and historian docs in the
WORKTREE branch, never merged: 84 CSVs `git rm --cached`-ed, `.gitignore` expanded,
`docs/PROJECT_HISTORY.md` + `docs/DATA_SOURCES.md` updated (Phase 15),
`docs/DAILY_AUTOMATION_FLOW.md` created, `production/trading/rel_vol_live.py`
dead-code deletion (227 lines: `TradierRelVol`, `RealtimeRelVolCache`,
`compute_rel_vol()` — all verified unreferenced).
**Steps** (in the MAIN checkout):
1. Copy from worktree → main: `.gitignore`, `docs/PROJECT_HISTORY.md`,
   `docs/DATA_SOURCES.md`, `docs/DAILY_AUTOMATION_FLOW.md`.
2. `production/trading/rel_vol_live.py`: the worktree copy has the dead code
   removed BUT is based on pre-`8053170` main. Do NOT copy the file. Instead
   re-apply the deletion to main's current copy: delete class `TradierRelVol`,
   class `RealtimeRelVolCache`, and function `compute_rel_vol()` (keep
   `fetch_rel_vol_baseline`, `HybridRelVol`, `fetch_missing_floats`,
   `_upsert_floats_to_neon`, `DEFAULT_REL_VOL`). First confirm zero callers:
   `grep -rn "TradierRelVol\|RealtimeRelVolCache\|compute_rel_vol" production/ research/`
   must return only definitions/docstrings inside rel_vol_live.py itself. If ANY
   caller outside the file exists, skip the deletion, note it.
3. Untrack the CSVs on main:
   `git ls-files '*.csv' | while IFS= read -r f; do git rm --cached "$f"; done`
   (84 files expected; the new .gitignore keeps them ignored afterward).
4. Also update `docs/DAILY_AUTOMATION_FLOW.md` before committing: mark items
   fixed this evening — 5.1 (`322b148`), 5.2 (`8877566`/`ae533f2`),
   session-capture (`147372a`), scalp hang (`5a1f0e0`), micro-pullback retry
   (`2a6bdba`), micro-pullback dashboard (`9412848`/`f8a6bca`). The worktree copy
   already reflects most of this; sanity-check it reads correctly.
**Verify**: py_compile rel_vol_live.py; import check
`cd production && python -c "import sys; sys.path.insert(0,'.'); from trading.rel_vol_live import HybridRelVol, fetch_rel_vol_baseline, fetch_missing_floats"`;
full 77-test suite; parity audit on commit (2 known failures only).
**Commit** (can be 2: `chore(hygiene): ...` for gitignore+CSVs+dead code,
`docs(historian): ...` for the 3 docs). Push before cutoff.

---

## PHASE B — Automation build (highest value, moderate risk, test via workflow_dispatch)

### B1. Automate the post-session report (kills the biggest manual daily chore)
**Why**: `session_report.py` is THE thing that writes real trades into Neon
`live_trades` (dashboard Trade History now reads from it, `8877566`). Today it
still requires a human to run it. Memory: `memory/log_persistence_todo.md`,
`memory/session_report_routine.md`. As of tonight it reads logs from Neon
`session_logs` (survives deploys), so it can run from GitHub Actions with no
Render-disk dependency.
**Steps**:
1. New workflow `.github/workflows/session-report.yml`:
   - cron `15 16 * * 1-5` (12:15 PM ET — after both strategy windows end 11:45 ET
     and after the 12:00 PM capture) + `workflow_dispatch`.
   - ubuntu-latest, checkout main, setup-python 3.11,
     `pip install -r production/requirements-deploy.txt` (verify that file contains
     `psycopg2-binary`, `requests`, `python-dotenv`, `pytz`; if `yfinance` etc. make
     install slow that's fine, correctness first).
   - Env from repo secrets: `NEON_CONNECTION_STRING`, `JTRADER_API_KEY`,
     `TRADIER_PRODUCTION_TOKEN`. **Check which of these already exist as repo
     secrets**: `gh secret list` (unset `GITHUB_TOKEN` env var first so gh uses
     keyring auth — known gotcha from today). `JTRADER_API_KEY` exists (used by
     session-capture.yml). For any missing secret, set it from
     `production/.env.render.dec`: `gh secret set NAME --body "..."`.
   - Run: `python production/data/live_capture/session_report.py --skip-pull`
     with `DB_DSN` set to the Neon string. `--skip-pull` because pull_live_bars
     targets the local Timescale DB, not needed here; Neon `session_bars` already
     captures bars via `persist_session`.
   - Step to append the report stdout to the workflow summary
     (`>> $GITHUB_STEP_SUMMARY`) so the user can read it from the Actions tab.
2. Test with `gh workflow run session-report.yml` then `gh run watch`/`gh run view`
   — expect it to parse Jul 1's logs from Neon and print the 6-trade table
   (idempotent: live_trades upserts on conflict, safe to re-run).
3. **Guard against double-persist noise**: session_report only INSERT...ON CONFLICT
   UPDATEs, so re-runs are safe. Confirm row count for `trade_date='2026-07-01'`
   in `live_trades` is still 6 after the test run (not 12).
**Verify**: green workflow run + Neon row count unchanged + table in step summary.
**Commit**: `feat(automation): daily post-session report via GitHub Actions (12:15 PM ET)`
**Abort if**: workflow needs more than 3 debug iterations — leave the yml
uncommitted (or committed but with cron commented out) + notes.

### B2. Fix stale-count fallback in session-capture (small follow-on)
**Why**: `session-capture.yml` pulls `/trades` — now Neon-backed (good), but also
`/logs` (ring buffer, wiped by deploys) and `/bars_dump` (ephemeral). That's
acceptable; but `generate_journal.py`'s journal for a day with a mid-day deploy
will have sparse logs. Improvement: make `generate_journal.py` prefer Neon
`session_logs` the same way session_report.py now does (copy the
`fetch_logs_from_neon` approach; fall back to the `_logs.json` file if
`NEON_CONNECTION_STRING` is absent). Add `NEON_CONNECTION_STRING` secret to
session-capture.yml env.
**Verify**: run `generate_journal.py --date 2026-07-01 --session-dir data/sessions/`
locally — note: on Windows the `%-d` strftime at ~line 281 crashes
(`Invalid format string`); that's a Linux-only format code. EITHER fix it while
you're in the file (portable: `f"{session_date.day}"` composition or `%#d` guard) —
that's a real robustness win — or verify via the workflow_dispatch run on ubuntu
instead. Prefer fixing it.
**Commit**: `fix(journal): read logs from Neon session_logs + portable strftime`

---

## PHASE C — Investigations (read-only, zero deploy risk, do after 06:00 ET if needed)

### C1. Tradier zero-bars root cause (MQ / BACC / GUACU, Jul 1)
**Why**: These 3 armed scalp candidates received ZERO bars all session, which
hung the entry loop (hang fixed in `5a1f0e0`, but the missing DATA is unexplained).
Memory: `memory/deploy_during_cron_incident.md` open item 1.
**Steps**:
1. Pull Jul 1 1-min timesales for each from Tradier prod
   (`https://api.tradier.com/v1/markets/timesales`, token
   `TRADIER_PRODUCTION_TOKEN` from `.env.render.dec`,
   `interval=1min, start=2026-07-01T09:30, end=2026-07-01T11:00, session_filter=all`).
   Also `/v1/markets/quotes` for each symbol now.
2. Compare against a control symbol that DID get bars (TC, EHGO).
3. Hypotheses to test: (a) genuinely zero prints in the window (check volume via
   Alpaca daily bar too), (b) symbol-format issue (units/warrants — GUACU looks
   like a SPAC unit, `.U`/`-U` suffix mismatch), (c) Tradier just doesn't carry it.
4. Write findings → new numbered lesson in `docs/DATA_SOURCES.md` "Lessons
   Learned" + append to `memory/deploy_during_cron_incident.md`.
5. IF the cause is "illiquid/no prints" → note that the wall-clock fallback is the
   correct final fix, close the item. IF symbol-format → propose (do NOT implement)
   a normalization in the scanner; leave a note for the user.
**Commit**: docs-only, `docs(data): lesson — why some armed symbols get zero Tradier bars`

### C2. Short-squeeze data source research (research doc only, NO code)
**Why**: JEM Jun 30 scored #1 but was the wrong setup (squeeze, not momentum gap).
Memory: `memory/short_squeeze_detection.md`. Anti-overfit rule: needs backtestable
data BEFORE any filter is built (`memory/live_filter_backtest_challenge.md`).
**Steps**: WebSearch for free/cheap short-interest + borrow-rate data with
HISTORY (backtestable): FINRA short interest (bi-monthly, free), Fintel, Ortex,
ChartExchange, Interactive Brokers FTP, SEC fails-to-deliver data. For each:
cost, update frequency, history depth, API availability. Write
`research/short_squeeze_data_sources.md` with a comparison table + recommendation
+ proposed tag-first (never filter-first) experiment design.
**Commit**: `docs(research): short-squeeze data source survey`

### C3. Corporate-actions detection research (research doc only, NO code)
**Why**: JBDI Jun 30 was a reverse-split artifact traded as a gap (-$36.52).
Memory: `memory/corporate_actions_filter.md`.
**Steps**: Survey sources for same-day corporate-action awareness: Alpaca
corporate-actions API (v2 announcements — check whether free tier includes it),
Polygon reference splits endpoint (free tier?), NASDAQ daily list, Financial
Modeling Prep. Also note the cheap heuristic: reverse split ⇒ prior_close from
daily bar ≠ split-adjusted quote ⇒ absurd gap% (JBDI showed as huge gap) + tiny
share count. Write `research/corporate_actions_detection.md`: sources table +
heuristic proposal + how to backtest it against the 2021-2025 gapper universe.
**Commit**: `docs(research): corporate-action / reverse-split detection survey`

### C4. Deploy/restart resilience — design doc only (NO implementation)
**Why**: Secondary cause from Jul 1: deploys near 7:00 AM ET kill the session
process; the ephemeral `session_started_date.txt` guard both wipes on deploy AND
can't resume a half-done session. Startup auto-trigger re-runs from scratch.
**Steps**: Read `production/api/server.py` (startup/auto-trigger logic),
`session_job.py` (`is_session_started_today`, `run_daily_sessions`),
`.github/workflows/runner-watchdog.yml`. Write
`docs/SESSION_RESILIENCE_DESIGN.md` covering: (1) move the session-started flag
to Neon (survives deploys), (2) phase-level checkpoints (scan done / scalp done /
phase-3 done) so a restarted process can skip completed phases and re-enter
monitoring for open positions (positions recoverable from Alpaca
`/v2/positions`), (3) simplest-thing-first option: a deploy-window guard script
+ documented rule "no pushes 06:00–12:00 ET", (4) recommendation + effort
estimate for each. **User decides; do not implement.**
**Commit**: `docs(design): session resilience vs deploys — options`

---

## PHASE D — Blocked / DO NOT ATTEMPT tonight (for completeness)

- **Micro-pullback validate_batch** — needs local Docker/Postgres (`mp_v1` Optuna
  study only exists there; Docker Desktop was down and starting it needs the user).
- **`session_runs` empty-table recheck** — needs tomorrow's live session data.
- **Parity audit known failures** (scalp `rank_candidates`, VWAP `max_float` in
  sim) — sim changes require backtest re-validation; user call.
- **Multi-candidate entry "arm top 5"** (`memory/multi_candidate_entry.md`) —
  scalp already arms MAX_ARMED with MAX_CONCURRENT=3; raising limits changes
  trade behavior → needs user + validation.
- **Premarket scan interval** (`memory/premarket_scan_interval.md`) — hybrid
  60s/5min scan appears ALREADY IMPLEMENTED (`run_scalp_session` premarket loop).
  Optional 5-min read-only check: if confirmed, update that memory file to DONE
  and note it. No code.
- **Anything touching live order/entry/exit behavior.**

---

## Recommended execution order & rough budget

A1 → A2 → A3 → A4 → push checkpoint → B1 → B2 → push checkpoint → C1 → C2 → C3 → C4.
Phases A+B are the pushable ones; front-load them long before the 06:00 ET cutoff.
Phase C is read-only/docs and safe anytime (docs-only pushes are still pushes —
if past cutoff, commit locally, don't push).

## End-of-run handoff (required)

Write a summary section at the bottom of this file: per task — DONE/SKIPPED/BLOCKED,
commit hashes, anything needing user decision. Update
`memory/MEMORY.md` + relevant topic memory files for completed items (follow the
existing format). Do NOT mark anything "verified" that wasn't actually verified.

---

## Progress Log (agent appends here)

- A1 DONE — TradierBarPoller log reworded, py_compile clean, commit `a6f5889`.
- A2 DONE — session_job.py docstring 8:55→7:00 (`3104028`); TradeHistory.tsx empty-state text fixed, tsc+build clean, pushed dashboard `10c10bd`.
- A3 DONE — 3 line-ending-only files reverted (`git diff --ignore-all-space` empty); `.env.example` deletion confirmed deliberate (never re-added since Jun 17 cleanup), staged via `git rm` for A4 commit.
- A4 DONE (partial) — gitignore + 3 docs harvested; found+fixed gitignore inline-comment bug (patterns with trailing `# comment` matched NOTHING — root cause CSVs were ever tracked); 83 CSVs untracked (`1d960ee`); docs commit `f7ce1d0`. **rel_vol_live.py dead-code deletion SKIPPED**: live callers now exist on main — live_micro_pullback_runner.py:163 uses TradierRelVol, :50 imports compute_rel_vol; test_rel_vol_baseline.py tests compute_rel_vol. Worktree audit predates MP runner. Needs user decision: migrate MP runner to HybridRelVol first, then delete. 77 tests pass.
- Phase A pushed `406c8a7`.
- B1 DONE — `.github/workflows/session-report.yml` (`a9c2e3e`), TRADIER_PRODUCTION_TOKEN secret set (NEON/JTRADER already existed). workflow_dispatch test run 28562317417 GREEN first try: parsed Jul 1 from Neon logs, 6-trade table in step summary, persisted; live_trades count for 2026-07-01 still 6 after re-run (idempotent confirmed).
- B2 DONE (`774dc85`) — generate_journal.py prefers Neon session_logs (falls back to _logs.json), `%-d` strftime fixed portably (Windows crash gone — verified by running locally on Windows against real Jul 1 Neon logs, FILLED lines present in journal). session-capture.yml gains NEON_CONNECTION_STRING env + psycopg2 install.
- C1 DONE (`8022669`) — root cause: MQ/BACC never watched (screened out 9:25 — MQ float 367M, BACC rel_vol 0.00); GUACU is a SPAC unit with 8 prints ALL DAY (first 11:46 ET) = genuine illiquidity, no symbol-format issue. Wall-clock fallback is correct final fix. DATA_SOURCES lesson 15 + memory updated; item closed.
- C2 DONE (`5ce772a`) — research/short_squeeze_data_sources.md: FINRA bi-monthly SI (free, archives to 2014, API) recommended; SEC FTD supplement; Ortex/Fintel deferred on cost; tag-first experiment design.
- C3 DONE (`20e23f1`) — research/corporate_actions_detection.md: Alpaca corporate-actions announcements (keys already in hand) + price/volume heuristic fallback; Polygon splits history as backtest ground truth.
- C4 DONE (`7490392`) — docs/SESSION_RESILIENCE_DESIGN.md: 3 options + effort table; recommend push-window guard → Neon flag w/ heartbeat → position-reconcile slice of phase checkpoints. User decides.

## End-of-run summary

| Task | Status | Commit(s) |
|---|---|---|
| A1 bar-poller log reword | DONE | `a6f5889` |
| A2 stale docstring + frontend text | DONE | `3104028`, dashboard `10c10bd` (pushed) |
| A3 line-ending noise + .env.example | DONE | (folded into `1d960ee`) |
| A4 worktree harvest | DONE except rel_vol dead-code (skipped — see below) | `1d960ee`, `f7ce1d0` |
| B1 session-report workflow | DONE, tested green (run 28562317417), idempotent | `a9c2e3e` |
| B2 journal Neon logs + strftime | DONE, tested locally on Windows | `774dc85` |
| C1 zero-bars root cause | DONE, item closed | `8022669` |
| C2 squeeze data survey | DONE | `5ce772a` |
| C3 corp-actions survey | DONE | `20e23f1` |
| C4 resilience design | DONE (docs only) | `7490392` |

**Needs user decision:**
1. rel_vol_live.py dead-code deletion BLOCKED — live_micro_pullback_runner.py uses
   `TradierRelVol` (line 163) + `compute_rel_vol`; migrate MP runner to HybridRelVol
   first (same fix scalp/VWAP got Jun 30), then delete + drop test_rel_vol_baseline.py.
2. SESSION_RESILIENCE_DESIGN.md — pick option(s); recommend starting with the
   pre-push window guard.
3. Squeeze + corp-actions research docs propose FINRA SI backfill and Polygon
   splits pull — approve before any code.

**Bonus find:** .gitignore trailing inline comments made several patterns match
NOTHING (root cause the CSVs were ever tracked). Fixed in `1d960ee`.

**Watch tomorrow (Jul 2):** session-report.yml first scheduled run 12:15 PM ET;
session-capture journal now reads Neon logs; incremental live-state writes
(`322b148`) first live confirmation; scalp wall-clock fallback day 1/3.
