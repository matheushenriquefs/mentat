---
name: mentat-orchestrate
description: >
  Fan out multiple plans in parallel, land them serially onto a holding branch.
  Use when you want to orchestrate a batch of plan slices across worktrees.
metadata:
  version: "0.1.0"
---

Hybrid orchestrator: one bin, three stage modules (`fan_out`, `land_queue`, `final_review`), four subcommands. Reads plan frontmatter to partition plans into anchored (HITL) and auto-spawned (AFK) groups. Spawns AFK plans in parallel via `ProcessPoolExecutor`; runs HITL plans in the current session. Lands all chunks serially onto the holding branch with gate checks.

## How to invoke

```
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py run [--harness <n>] [--model <s>] [--dry-run] <holding-branch> <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py fan-out <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py land-queue <holding-branch>
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py final-review <session>
```

## Routing algorithm (B6 design)

```
1. Read frontmatter of each plan: id, class, blocked_by.
2. Topological sort by blocked_by (raise on cycle).
3. Partition in topo order:
   - HITL plans → anchored_here
   - AFK with downstream HITL dep → anchored_here
   - AFK with no downstream HITL dep → auto_spawn
4. Spawn auto_spawn in parallel (ProcessPoolExecutor).
   Print track command immediately after spawn.
5. Run anchored_here serially in current session.
6. Poll/wait for auto_spawn completions.
7. Land all completed chunks (anchored + auto_spawn) serially onto holding.
8. final-review at end of queue (advisory).
9. Exit 0 all-landed; 1 if any ejected.
```

## Verdict JSONL shape

```json
{"slug": "...", "outcome": "success|eject", "tip": "...",
 "reason": "...", "conflicted_files": [...], "resume_cmd": "...", "findings": [...]}
```

`outcome ∈ {success, eject}` · `reason ∈ {rebase-conflict, gate-fail, not-ff, implement-fail, hitl-ambiguity}`

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All chunks landed |
| 1 | ≥1 chunk ejected |
| ≥2 | Tool error |
