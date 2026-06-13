# STATUS — where the project is right now

**One-screen current state. Rewrite the top sections each working session.**
History goes in `docs/PROJECT_HISTORY.md`; durable facts in `memory/`; this file is
the "what's true today / what's next / what's blocking" snapshot an agent reads first.

_Updated: 2026-06-13 (Sat)_

---

## Deployed / live

- **jTrader** runs on Render: daily job = Opening Bell Scalp (9:30–9:40) → VWAP
  Reclaim (10:00–11:30), **paper mode** (Tradier sandbox orders, production token
  for data). Account ~$100k paper.
- **Main is AHEAD of what's deployed** — this weekend's commits are NOT deployed
  (held intentionally; no push tonight). Deploy off-hours before Mon, never
  08:00–11:45 ET. Deploys wipe Render ephemeral capture — pull bars first.

## Live configs in use

- **Scalp**: trial 173. ⚠️ `max_entry_bars=30` is a PAPER override (validated = 4)
  — restore to 4 before live money.
- **VWAP**: trial 173. ⚠️ **STALE** — sealed-2025 number does not reproduce on the
  current DB; do not trust for live until re-validated (task #20).

## Next actions

Full ranked backlog → **`docs/STRATEGY_ROADMAP.md`** (current, post-pivot; the root
`ROADMAP.md` is superseded). Immediate:
1. **Tue (after Mon session)**: `pull_live_bars.py --date 2026-06-15` then
   `daily_validation.py --date 2026-06-15` — first real sim/live parity test with
   the new `--date` endpoint support.
2. **Before Mon open (optional, to make the parity fixes live)**: re-push data
   branch (`export_rel_vol_baseline.py --push`) + set `GITHUB_TOKEN` on Render +
   off-hours redeploy.
3. **P0 — VWAP non-reproduction (task #20):** use `research/maintenance/db_fingerprint.py`
   to fingerprint the sealed range, commit the baseline, re-validate VWAP 173 on the
   fingerprinted DB, THEN seal. No live cutover until a reproducible number exists.
4. **P1 — corpus-backed safety nets:** daily risk circuit breakers (max-loss/green-to-red/
   give-back-half — corpus's #1 P&L destroyer) + market-temp gate (cold 53.9% vs hot 71.9% WR).
5. **P2 — strategy #3 micro-pullback** for the empty 9:40–10:00 window (74.3% WR).

## Blockers / watch

- `GITHUB_TOKEN` not yet set on Render → live runners fall back to rel_vol=10.0
  (filter no-op) and no floats. Harmless (no crash), but parity fixes #2/#3 are
  dormant until set + redeployed.
- Jun 12 (AERT) live capture likely unrecoverable (today-only endpoint + possible
  auto-deploy wipe). `--date` endpoint fix prevents this going forward (needs deploy).

## Parity status

See `docs/PARITY.md`. 3 gaps fixed `4ae4cf7` (news gate, float filter, VWAP
rel-vol timing); remaining are inherent (cross-vendor / live-timing) or the
documented `max_entry_bars` override.

## Uncommitted / loose ends

- Many untracked research artifacts (backfill progress JSON, optimizer findings,
  diagnostics) — gitignored or pending a hygiene pass (see historian flags).
