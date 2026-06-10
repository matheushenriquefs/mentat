# ADR 0004: Parallel orchestration (folds ADR-0010 HITL + ADR-0011 decomp + ADR-0012 harness-registry)

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-09 (v2 — hybrid 1-bin+3-modules shape; Python ProcessPoolExecutor;
folds 0010 hitl-routing + 0011 decomp + 0012 harness-registry)

## Context

Orchestration shape evolved through ADRs 0010, 0011, 0012. Shell-era 3-bin pattern
(`mentat-fan-out`, `mentat-land-queue`, `mentat-final-review`) maps naturally to
Python stage modules under one bin. HITL routing contract and harness registry
folded here.

## Decision

**Shape: one bin + three stage modules + four subcommands.**

- `mentat-orchestrate run [--harness=<n>] [--model=<s>] [--dry-run] <holding> <plan-ref>+`
- `mentat-orchestrate fan-out <plan-ref>+` — debug: spawn N plans headless; stdout = chunk slugs
- `mentat-orchestrate land-queue <holding-branch>` — debug: stdin = slugs; stdout = verdict JSONL
- `mentat-orchestrate batch-review <session>` — debug: re-run batch review

Stage modules under `scripts/`: `fan_out.py`, `land_queue.py`, `batch_review.py`.

**Routing partition (HITL contract folded from ADR-0010):**

Read each plan's `class: AFK|HITL` frontmatter. Topological sort by `blocked_by`.
- `HITL` plans → anchored in current interactive session.
- `AFK` plans with no downstream HITL dep → auto-spawned headless.
- `AFK` plans downstream of HITL → anchored (HITL must complete first).

AFK headless contract: harness adapter invoked with `--disallowedTools AskUserQuestion`
+ system clause forbidding self-answer. Exit `42` = `hitl-ambiguity` (AFK adapter
detected ambiguity). HITL: interactive, normal.

**Concurrency:** `concurrent.futures.ProcessPoolExecutor` — subprocess per chunk = isolation.

**Harness registry (folded from ADR-0012):** claude-code + cursor hard-coded as
Python adapters in `mentat-implement/scripts/harness/`. No JSONC file.
Selection: `~/.mentat/config.jsonc` `harness:` key; `--harness` flag overrides.

**Verdict JSONL shape:**
```
{slug, status, tip, reason?, conflicted_files?, resume_cmd?, findings?}
  status ∈ {success, eject}
  reason ∈ {rebase-conflict, gate-fail, not-ff, implement-fail, hitl-ambiguity}
```

Exit codes: 0 all-landed; 1 partial; ≥2 tool error.

## Consequences

Shell bins `mentat-fan-out`, `mentat-land-queue`, `mentat-batch-review` replaced by
debug subcommands. Old ADRs 0010, 0011, 0012 archived. Docker required per worktree.
Track prompt prints immediately after spawn (not at end) so user can monitor while
anchored plans run. `mentat-session track` remains the live view.
