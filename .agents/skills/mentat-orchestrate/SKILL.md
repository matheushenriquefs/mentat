---
name: mentat-orchestrate
description: >
  Fan out multiple plans in parallel, land them serially onto a holding branch.
  Use when you want to orchestrate a batch of plan slices across worktrees.
---

Hybrid orchestrator: one bin, three stage modules (`fan_out`, `land_queue`, `batch_review`), four subcommands. Reads plan frontmatter to partition plans into anchored (HITL) and auto-spawned (AFK) groups. Spawns AFK plans in parallel via `ProcessPoolExecutor`; runs HITL plans in the current session. Lands all chunks serially onto the holding branch with gate checks.

## How to invoke

```
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py run [--harness <n>] [--model <s>] [--dry-run] <holding-branch> <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py fan-out <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py land-queue <holding-branch>
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py batch-review <session>
```

## Routing algorithm

```
1. Read frontmatter of each plan: id, class, blocked_by.
2. Topological sort by blocked_by (raise on cycle).
3. Partition in topo order:
   - HITL plans → anchored_here
   - AFK with downstream HITL dep → anchored_here
   - AFK with no downstream HITL dep → auto_spawn
4. Spawn auto_spawn in parallel (ProcessPoolExecutor).
   Print track command immediately after spawn.
5. Emit `chunk.spawned{harness:"hitl-in-session"}` per anchored plan and
   return control. Caller queries the audit log
   (`mentat-log query chunk.spawned --session=$MENTAT_SESSION`) and invokes
   `/mentat-implement <slug>` in-session per anchored slug, then re-invokes
   `orchestrate land-queue <holding>` with the HITL slugs on stdin. Orchestrate
   never subprocess-runs HITL implement — interactivity would be lost.
6. Poll/wait for auto_spawn completions.
7. Land auto_spawn chunks serially onto holding (HITL chunks land in the
   follow-up `land-queue` call described in step 5).
8. batch-review at end of queue (advisory).
9. Exit 0 all-landed; 1 if any ejected.
```

## Verdict JSONL shape

```json
{"slug": "...", "status": "success|eject", "tip": "...",
 "reason": "...", "conflicted_files": [...], "resume_cmd": "...", "findings": [...]}
```

`status ∈ {success, eject}` · `reason ∈ {rebase-conflict, gate-fail, not-ff, implement-fail, hitl-ambiguity}`

## Exit codes

| Code | Meaning |
|---|---|
| 0 | All chunks landed |
| 1 | ≥1 chunk ejected |
| 64 | CLI arg parse error / missing plan ref |
| 65 | Malformed plan frontmatter or cycle in blocked_by graph |
| 66 | Plan slug not found |
| 69 | Container down when spawning a chunk |
| 70 | Unhandled Python exception in stage module |

## Rules

- Plans without `blocked_by` run in parallel with any other independent plan.
- HITL plans always anchor in the calling session; AFK plans can auto-spawn.
- AFK plan with a downstream HITL dep anchors in the calling session.
- Land queue is serial: each chunk rebases onto the tip the previous one left.
- Gate required on each chunk before land; ejected chunk leaves worktree intact.
- `batch-review` is advisory; never blocks the batch.
- All emit calls route through `mentat-log emit` per ADR-0007.
- Doctor handoff fires after batch settle; never blocks shell return.

## Constraints

- Holding branch must have no own commits; only fast-forward allowed (ADR-0002).
- Container required per chunk (ADR-0004). Exit 69 if container unavailable.
- Plan class read from frontmatter only; no env var override.
- `--dry-run` prints what would run; does not spawn or land.
- Session id from `$MENTAT_SESSION` for audit events.
- `batch-review` is always advisory; ejected counts do not affect its exit code.

## Doctor handoff

Non-zero exit (`≥1` chunk ejected, container miss, malformed plan, unhandled exception) → spawn `mentat-session doctor --reason=batch-failed` non-blocking after the batch settles. Doctor failure is swallowed; the batch exit code is authoritative.
