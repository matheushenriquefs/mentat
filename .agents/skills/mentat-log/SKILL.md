---
name: mentat-log
description: >
  Emit, validate, query, and prune mentat audit log entries.
  Use when the user wants to inspect orchestration history, debug a failed batch,
  or write a custom event from a script.
metadata:
  version: "0.1.0"
---

Emit, validate, query, and prune structured JSONL audit entries under `~/.mentat/logs/`. Owns the canonical `EVENT_CATALOG` — the single source of truth for the 9 event types that all mentat skills emit.

## How to invoke

```
python3 ~/.agents/skills/mentat-log/scripts/log.py <subcommand> <args>
```

Subcommands: `emit`, `validate`, `query`, `prune`.

## Event catalog

| Event | Required payload fields |
|---|---|
| `plan.started` | `path` |
| `plan.succeeded` | `path` |
| `plan.failed` | `path`, `reason` |
| `chunk.spawned` | `slug`, `plan`, `harness`, `worktree` |
| `chunk.landed` | `slug`, `sha`, `holding` |
| `chunk.ejected` | `slug`, `reason`, `where` |
| `gate.evaluated` | `gate`, `verdict`, `severity`, `message` |
| `review.submitted` | `reviewer`, `score`, `threshold`, `verdict` |
| `batch.reviewed` | `session`, `summary` |

`chunk.ejected.reason` ∈ `implement-failed | gate-failed | rebase-conflicted | not-ff | hitl-required`

## When to emit each

- `plan.started` / `plan.succeeded` / `plan.failed` — wrap any plan-writing or plan-execution lifecycle.
- `chunk.spawned` — immediately after `mentat-orchestrate` creates a headless worktree.
- `chunk.landed` — after a successful FF-merge onto the holding branch.
- `chunk.ejected` — when a chunk fails gate, has a rebase conflict, or needs HITL.
- `gate.evaluated` — each gate result (code or LLM).
- `review.submitted` — each reviewer score in the ADR-0003 gate pass.
- `batch.reviewed` — end-of-queue advisory final review.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MENTAT_LOG_PATH` | `~/.mentat/logs` | Root log directory |
| `MENTAT_SESSION` | `manual-<ts>-<pid>` (loose) | Session ID |
| `MENTAT_REPO` | `basename(cwd)` | Repo name for log path |
| `MENTAT_SLUG` | `manual-<pid>` | Agent slug for log filename |

Log dir created with `mode=0o700` on first write. Reject + sidecar on: unknown event, missing required field, non-JSON payload.
