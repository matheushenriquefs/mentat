---
name: mentat-log
description: >
  Emit, validate, query, and prune mentat audit log entries.
  Use when the user wants to inspect orchestration history, debug a failed batch,
  or write a custom event from a script.
---

Emit, validate, query, and prune structured JSONL audit entries under `~/.mentat/logs/`. Owns the canonical `EVENT_CATALOG` — the single source of truth for the 9 event types that all mentat skills emit.

## How to invoke

Terminal tool — run on PATH (no slash form; this is not a harness slash command):

```
mentat-log <subcommand> <args>
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
- `batch.reviewed` — end-of-queue advisory batch review.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MENTAT_LOG_PATH` | `~/.mentat/logs` | Root log directory |
| `MENTAT_SESSION` | `mentat-manual-<ts>-<pid>` (loose) | Session ID |
| `MENTAT_REPO` | `basename(cwd)` | Repo name for log path |
| `MENTAT_SLUG` | `mentat-manual-<pid>` | Agent slug for log filename |

Log dir created with `mode=0o700` on first write. Reject + sidecar on: unknown event, missing required field, non-JSON payload.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation failure or prune dry-run found violations |
| 64 | CLI arg parse error / missing subcommand |
| 70 | Unhandled Python exception |

## Rules

- `EVENT_CATALOG` in `log.py` is single source of truth; no event emitted outside catalog.
- Naming follows ADR-0007 §Naming policy: past-tense verbs, `resource.action` shape, sub-reasons live in payload not in name.
- Extend existing payloads with new fields; coin a new event only when handler logic genuinely diverges.
- `emit` writes atomically: temp file + rename, never partial append.
- `validate` reads all `.jsonl` files under `MENTAT_LOG_PATH`; exit 0 if all valid.
- `query` filters by `event`, `session`, `repo`, `since`, or `slug`; outputs JSONL to stdout.
- `prune` deletes entries older than `--days`; `--dry-run` prints without deleting.
- Sidecar file (`.bad`) written beside any rejected entry for forensics.

## Constraints

- Log path is `~/.mentat/logs/<repo>/<session>/<slug>.jsonl`.
- `mode=0o700` on log dir; log files `mode=0o600`.
- `emit` never raises on I/O error — logs to stderr, exits 0 (fire-and-forget contract).
- `validate` and `query` raise on I/O error — callers rely on exit code.
- No external dependencies; stdlib only.
