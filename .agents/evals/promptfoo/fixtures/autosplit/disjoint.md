# Plan brief: mentat bin/ refactor (disjoint groups)

## Goal

Refactor `mentat/.agents/bin/` and `mentat/.agents/agents/` to use shared lib helpers and standardized naming. The work falls into four groups with completely separate write-sets and no dependency chain between them.

## Groups

### Group A — lib helpers
Write-set: `.agents/bin/lib/strict.sh`, `.agents/bin/lib/log.sh`, `.agents/bin/lib/here.sh`
Work: create sourced helper files (strict mode, logging, self-locator). No dependency on B, C, or D.

### Group B — add agents/
Write-set: `.agents/agents/mentat-smell-reviewer.md`, `.agents/agents/mentat-plan-reviewer.md`
Work: add new reviewer agent files. No dependency on A, C, or D.

### Group C — add bin/
Write-set: `.agents/bin/mentat-release`, `.agents/bin/mentat-sync-upstream`, `.agents/bin/mentat-logs-prune`
Work: add new release + upstream management scripts. No dependency on A, B, or D.

### Group D — update docs
Write-set: `.agents/docs/mentat-architecture.md`, `AGENTS.md`, `CONTEXT.md`
Work: update cross-references to new names. No dependency on A, B, or C.

## Slices

- S1: create `lib/strict.sh`, `lib/log.sh`, `lib/here.sh` [Group A]
- S2: git mv agent files to `mentat-*` [Group B]
- S3: git mv bin files to `mentat-*` [Group C]
- S4: sed sweep docs for new names [Group D]

No slice in any group blocks a slice in another group. All four can run in parallel.
