# Plan brief: mentat package refactor (disjoint groups)

## Goal

Refactor `.agents/lib/` helpers and `.agents/agents/` reviewer set. The work falls into four groups with completely separate write-sets and no dependency chain between them.

## Groups

### Group A — lib helpers
Write-set: `.agents/lib/support/paths.py`, `.agents/lib/logging.py`, `.agents/lib/here.py`
Work: create stdlib helper modules (canonical path resolution, structured logging, self-locator). No dependency on B, C, or D.

### Group B — add agents/
Write-set: `.agents/agents/mentat-smell-reviewer.md`, `.agents/agents/mentat-plan-reviewer.md`
Work: add new reviewer agent files. No dependency on A, C, or D.

### Group C — add release scripts
Write-set: `.agents/skills/mentat-release/scripts/release.py`, `.agents/skills/mentat-logs-prune/scripts/prune.py`
Work: add new release + log-rotation scripts. No dependency on A, B, or D.

### Group D — update docs
Write-set: `.agents/docs/mentat-architecture.md`, `AGENTS.md`, `CONTEXT.md`
Work: update cross-references to new names. No dependency on A, B, or C.

## Slices

- create `lib/support/paths.py`, `lib/logging.py`, `lib/here.py` [Group A]
- write reviewer files under `agents/` [Group B]
- write release + prune scripts under `skills/` [Group C]
- sweep docs for new names [Group D]

No slice in any group blocks a slice in another group. All four can run in parallel.
