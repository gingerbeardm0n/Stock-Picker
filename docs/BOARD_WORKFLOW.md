# Sprint Board Workflow

GitHub Issues is the sprint board for this repo (created 2026-07-08).
Board = **active work only**. Durable facts stay in memory/docs; history in git.
This replaces STATUS.md's TODO-list role.

## Columns (via `status:*` labels until Projects board is enabled)

```
Backlog → status:analysis → status:in-progress → status:awaiting-backtest → status:live-validation → Closed
```

- **Backlog** — no status label. Idea captured, not specced.
- **analysis** — being investigated / spec written on the issue.
- **in-progress** — actively worked (human or agent).
- **awaiting-backtest** — code ready but blocked on sim validation.
- **live-validation** — deployed; needs **3 consecutive clean trading days with
  zero code changes to that area**. A code change resets the counter (same rule
  as `DAILY_AUTOMATION_FLOW.md`).
- **Closed** — done AND validated. Regression = **reopen the same issue**, never
  open a duplicate; the history must stay attached.

View board: `gh issue list --label "status:awaiting-backtest"` etc.

## Type labels (exactly one per issue)

| Label | Meaning | Backtest required? |
|---|---|---|
| `bug` | Behavior wrong vs intent; fix restores intent | No |
| `infra` | Plumbing: deploys, CI, logging, dashboard, persistence | No |
| `strategy-change` | Alters which trades happen or how (entry/exit/filters/sizing/retry/fallback behavior) | **Yes — cannot skip awaiting-backtest** |
| `research` | Investigation task, read-only output | N/A |

Extra tag: `parity-gap` = live behavior the sims don't model.

**The hard-learned rule:** changes disguised as bug fixes are often
`strategy-change`. Litmus test: *does the fix change any trade that would have
happened?* Entry retries, order-type fallbacks, timing fallbacks → all
strategy-change, all need sim numbers before Done. (Audit 2026-07-08 found
three of these shipped unvalidated: #7, #8, #9.)

## Junior-dev agent workflow

Roles:

| Role | Who | Job |
|---|---|---|
| Triage | user + main Claude session | Write card specs, review output, approve merges |
| Investigator | small-model subagent | Read-only: audit / locate / compare, return findings |
| Builder | subagent | Bounded 1-2 file change from a card spec |
| Backtester | subagent | Run sim variant, return numbers table |

Flow per card:
1. Main session writes a **self-contained spec** on the issue (goal, files,
   method, exit criteria). The spec IS the agent prompt — agents start cold,
   carrying no conversation history. That's the token win.
2. Spawn **one agent at a time** (sequential, standing rule — no parallel
   batches without explicit user approval).
3. Agent output posted as an issue comment; main session + user review.
4. Commits reference the issue (`#N` in message) so the card accumulates its
   own history.

Standing constraints that apply to all agents:
- Never edit sim/engine logic without user-approved backtest validation.
- Never place/modify/cancel broker orders.
- No pushes to main before 12:00 ET on trading days.
- File placement per `FILE_PLACEMENT_GUIDE.md`.

## Enabling the real Projects board (optional)

Issues + status labels are sufficient. For a drag-and-drop board:

```
gh auth refresh -s project,read:project
gh project create --owner gingerbeardm0n --title "jTrader Sprint Board"
```

Then link the repo and map columns to the `status:*` labels.
