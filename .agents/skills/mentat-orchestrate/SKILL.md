---
name: mentat-orchestrate
description: >
  Fan out multiple plans in parallel, land them serially onto a holding branch.
  Use when you want to orchestrate a batch of plan slices across worktrees.
---

Hybrid orchestrator: one bin, three stage modules (`fan_out`, `land_queue`, `batch_review`), four subcommands. Reads plan frontmatter to partition plans into anchored (HITL) and auto-spawned (AFK) groups. Spawns AFK plans in parallel via `ProcessPoolExecutor`; runs HITL plans in the current session. Lands all chunks serially onto the holding branch with gate checks.

## How to invoke

Slash form (in-harness) leads; each runs the `python3 .../orchestrate.py <sub> …` underlying call.

```
/mentat-orchestrate run [--harness <n>] [--model <s>] [--dry-run] <holding-branch> <plan-ref>+
/mentat-orchestrate fan-out <plan-ref>+
/mentat-orchestrate land-queue <holding-branch>
/mentat-orchestrate batch-review <session>
```

Subcommands: `run`, `fan-out`, `land-queue`, `batch-review`. `run` takes the holding branch FIRST, then plan refs — the inverse of `implement <plan-ref>` (no branch, does NOT land). The arg-order asymmetry is by design: orchestrate lands a batch onto a holding branch, implement runs one plan in-session with no branch. Not an inconsistency.

## Routing algorithm

```
0. Expand parent-index plans: any plan with siblings:[…] in frontmatter is a
   parent index. It is replaced by its listed sibling plans before topo sort.
   Parent index must have empty blocked_by (exit 65 otherwise). A sibling file
   not found → exit 66. Nested parent indexes (sibling itself has siblings) →
   exit 65. Plans without siblings: parse unchanged.
1. Read frontmatter of each plan: id, class, blocked_by.
2. Topological sort by blocked_by (raise on cycle).
3. Partition in topo order (via `scheduler.partition`):
   - HITL plans → anchored_here
   - AFK with downstream HITL dep → anchored_here
   - AFK with upstream HITL dep → anchored_here (caller must drive the
     upstream HITL in-session before the downstream AFK can spawn)
   - AFK with no HITL anywhere in the dep chain → auto_spawn
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
   follow-up `land-queue` call described in step 5). `land_queue.drain`
   pulls chunks via `Scheduler.next_ready` — topo order is respected, so
   `B(blocked_by=[A])` waits until `A.landed` even if B's chunk arrived
   first. Ejecting a chunk cascades to every downstream chunk as
   `chunk.ejected{reason:"upstream_ejected", upstream:<slug>}` —
   payload-only extension per ADR-0007, no rebase/gate fired for the
   cascaded slugs. Cycle / missing upstream → `status:"stalled"` with
   the pending list and exit 1.
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
| 65 | Malformed plan frontmatter or cycle in blocked_by graph; parent index has non-empty blocked_by; plan blocks on a parent-index slug; nested parent index |
| 66 | Plan slug not found; sibling plan file not found during parent-index expansion |
| 69 | Container down when spawning a chunk |
| 70 | Unhandled Python exception in stage module |

## Rules

- **Parent indexes** (`siblings: [a, b]` in frontmatter) are expanded before
  routing — passing the parent ref produces the same schedule as passing every
  sibling ref directly. Parent indexes must have empty `blocked_by`; they never
  participate in topo sort. No plan may reference a parent-index slug in its
  own `blocked_by`; use sibling slugs directly.
- Plans without `blocked_by` run in parallel with any other independent plan.
- HITL plans always anchor in the calling session; AFK plans can auto-spawn.
- AFK plan with a downstream HITL dep anchors in the calling session.
- AFK plan with an upstream HITL dep anchors in the calling session — its
  worktree can't safely spawn before the upstream HITL lands.
- Cross-chunk dep gating in `land-queue`: `Scheduler.next_ready` orders
  the drain by `blocked_by`; an ejected upstream cascades `upstream_ejected`
  to every downstream chunk without touching their worktrees.
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
- Config resolved as layered stack: CLI flag > `<repo-root>/.mentat/config.jsonc` > `~/.mentat/config.jsonc`. Scaffold repo overlay with `mentat-install --repo`.

## Doctor handoff

Non-zero exit (`≥1` chunk ejected, container miss, malformed plan, unhandled exception) → spawn `mentat-session doctor --reason=batch-failed` non-blocking after the batch settles. Doctor failure is swallowed; the batch exit code is authoritative.
