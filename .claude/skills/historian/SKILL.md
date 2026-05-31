---
name: historian
description: Project Historian & Custodian. Maintains docs/PROJECT_HISTORY.md — a timeline of what was built/changed/deprecated and a component index — by reading git history since the last entry, and audits the file tree for sprawl / dead code / misplaced files (flags only, never deletes). Run periodically. Triggers: "run historian", "update project history", "historian pass", "custodian pass", "/historian".
---

# Project Historian & Custodian

Keep `docs/PROJECT_HISTORY.md` current and the repo tidy. This project iterates fast and
sprawls; without upkeep we lose the "what/when/why" thread and accumulate dead/duplicate files.

## Two modes

- **Bootstrap (first run only):** done manually by the main agent from full session context +
  `git log`. If `docs/PROJECT_HISTORY.md` already exists with a populated timeline, you are NOT
  bootstrapping — do an incremental pass.
- **Incremental (every run after):** the normal job below.

## Incremental run — steps

1. **Find the watermark.** Read `docs/PROJECT_HISTORY.md`; note the last commit hash recorded in
   its Timeline (the "history watermark" line near the top).
2. **New history.** `git log <watermark>..HEAD --date=short --pretty="%ad | %h | %s"`. For each new
   commit, append a Timeline row: `date | hash | what landed | why (1 line)`. Group by day.
   Update the watermark line to the newest hash.
3. **Component index.** For files added/renamed/deleted since the watermark
   (`git diff --stat <watermark>..HEAD`), update the Component Index: add new key modules
   (path | purpose | status | since), mark superseded ones `deprecated` with `superseded-by`.
4. **Deprecations.** Note anything now dead (a function/file replaced by another). Don't delete —
   record it so humans know it's safe to remove.
5. **Custodian audit (FLAG ONLY — never delete/move without the user):** scan the tree against
   `FILE_PLACEMENT_GUIDE.md` / MEMORY file-org rules. Flag, in the Hygiene section:
   - root-level `.py` (rule: none except config.py)
   - dead code (defined-but-unreferenced; e.g. sim methods replaced by the orchestrator)
   - duplicate logic across files
   - stale docs (describe code that changed)
   - large data/binaries that should be gitignored (`.db`, `.parquet`, `.csv`, `.log`)
   - files not touched in a long time AND not imported anywhere
6. **Report.** Print a short summary: N commits folded in, new/deprecated components, top hygiene
   flags. Do NOT perform deletions — propose them; the user approves.

## How to run the scan

For a large tree, spawn ONE read-only subagent (caveman:cavecrew-investigator or general-purpose)
to do the git-log read + file-tree audit and return the updates, then apply them to
`docs/PROJECT_HISTORY.md` in the main thread. (This is an explicitly authorized agent — it does not
violate the "no unprompted parallel agents" rule.) For a small delta, just do it inline.

## Hard rules
- **Never delete or move files** — the custodian only *flags*. Deletions are the user's call.
- Keep `PROJECT_HISTORY.md` append-mostly: never rewrite history, only add + update statuses.
- One Timeline entry per commit (or per logical group); keep "why" to one line.
- If unsure whether something is deprecated vs active, mark it `unknown — verify` and flag it.
