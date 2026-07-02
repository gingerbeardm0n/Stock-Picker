# Session Resilience vs Deploys — Design Options (2026-07-02)

**Problem (Jul 1 incident, `memory/deploy_during_cron_incident.md`):**
Render redeploys kill the trading-session process mid-flight. Three stacked
weaknesses:

1. The 7:00 AM ET APScheduler cron fired, then a 7:07 ET deploy killed that
   process during its "wait until 8:00" sleep.
2. The only restart guard is `session_started_date.txt` on Render's **ephemeral
   disk** — a deploy wipes it, so the restarted process can't tell a session was
   in flight. (The startup auto-trigger in `server.py:78-83` then re-runs from
   scratch — which *saved* Jul 1, but only by luck of timing, and it always
   restarts from the very beginning.)
3. A restart mid-session cannot resume: premarket scan, scalp window, and the
   Phase-3 VWAP/micro-pullback launch all live in one `run_daily_sessions()`
   call with no checkpoints. A 9:35 restart would re-scan premarket data that
   no longer exists and orphan any open position (positions themselves are safe
   at Alpaca, but nothing would manage exits).

Current mitigations already in place: runner-watchdog.yml (5 wake/trigger slots
6:50–9:10 ET), `/trigger` idempotency via the same ephemeral flag, and the
"no push to main 08:00–11:45 ET" rule (operating rule, human-enforced).

---

## Option 1 — Move the session-started flag to Neon

**What:** Replace `_SESSION_STARTED_FILE` (`session_job.py:52-60`) with a
`session_runs` row (table already exists): write `(run_date, started_at,
status='running')` at kickoff; `is_session_started_today()` queries Neon
instead of the file. Update `status='complete'` at session end.

**Fixes:** double-start after deploy (guard survives wipe); gives the watchdog
and `/trigger` a truthful idempotency source instead of the dashboard
`last_run` heuristic.
**Does NOT fix:** a killed session stays killed — the flag would now *prevent*
the auto-trigger from restarting it at all. So Option 1 **must** ship with a
staleness rule (e.g. `status='running'` with no heartbeat for >10 min ⇒ treat
as dead, allow re-trigger) or it makes the Jul 1 outcome *worse*.

**Effort:** small — ~30 lines (one table write, one query, heartbeat column
updated from the existing poll loops). **Risk:** low, but the staleness rule
needs care.

## Option 2 — Phase-level checkpoints + resume

**What:** Break `run_daily_sessions()` into checkpointed phases recorded in
Neon (extend `session_runs` with a `phase` column):
`scan_done → scalp_done → phase3_launched → complete`.
On startup-auto-trigger, read the last checkpoint and:

- `scan_done`: reuse persisted candidates (already in `active_symbols` /
  session persistence) instead of re-scanning.
- `scalp_done`: skip straight to launching VWAP + micro-pullback.
- Any phase with possible open positions: **reconcile against Alpaca
  `GET /v2/positions`** first; re-enter monitoring/exit management for any
  live position instead of trading fresh.

**Fixes:** the actual failure mode end-to-end, including the scary one (open
position + restart = unmanaged position).
**Effort:** medium-large — touches `session_job.py`, all 3 runners (each needs
a "resume with existing position" entry point), and needs careful testing that
can only be fully proven on live days. Position-recovery logic is the hard 20%.

## Option 3 — Deploy-window guard (simplest thing first)

**What:** Two cheap layers:
1. **Documented rule tightened:** no pushes to main **06:00–12:00 ET** on
   weekdays (current rule starts at 08:00; Jul 1's killer deploys were 06:53
   and 07:07). Already adopted as the overnight-plan hard rule.
2. **Enforcement script:** a pre-push git hook (or CI check) that refuses to
   push to main during that window unless `ALLOW_TRADING_WINDOW_PUSH=1`.
   ~15 lines of shell; zero production-code risk.

**Fixes:** the *cause* (deploys during the window) rather than the *symptom*.
**Does NOT fix:** Render restarting on its own (instance recycling, crashes) —
rare but real on free tier.
**Effort:** trivial.

---

## Recommendation

Ship in this order:

1. **Option 3 now** (minutes, zero risk) — removes the self-inflicted cause.
2. **Option 1 next** (small), *with* the heartbeat/staleness rule — durable
   idempotency, and it's the foundation Option 2 builds on (same table).
3. **Option 2 last and incrementally** — start with the highest-value slice:
   on startup, reconcile Alpaca positions and, if any exist, enter
   exit-management-only mode (no new entries). That covers the dangerous case
   without the full phase-resume machinery; full scan/scalp checkpointing can
   follow if restarts keep happening after 1+3.

| Option | Effort | Risk | Covers |
|---|---|---|---|
| 3. Push-window guard | ~30 min | none | self-inflicted deploys |
| 1. Neon flag + heartbeat | ~2-3 h | low | double-start, truthful idempotency |
| 2a. Position-reconcile on startup | ~1 day | medium | orphaned open positions |
| 2b. Full phase checkpoints | 2-3 days | medium-high | full resume |

**User decision required — no implementation done.**
