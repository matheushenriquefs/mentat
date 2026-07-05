---
name: mentat-log
description: >
  Emit, validate, list, and prune mentat audit events.
  Use when the user wants to inspect orchestration history, debug a failed batch,
  or write a custom event from a script.
---

Emit, validate, list, and prune structured audit events. Canonical store: `~/.mentat/mentat.db` via `lib/store.py`. Owns `EVENT_CATALOG` — the single source of truth for event types all mentat skills emit.

## How to invoke

Terminal tool — run on PATH (no slash form; this is not a harness slash command):

```
mentat-log <subcommand> <args>
```

Subcommands: `emit`, `validate`, `list`, `prune`. (`query` is a deprecated alias for `list`.)

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

`chunk.ejected.reason` ∈ `implement-failed | gate-failed | rebase-conflicted | not-ff | hitl-required | …` (see `lib.events.EJECT_REASONS`)

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `MENTAT_DB` | `~/.mentat/mentat.db` | Canonical sqlite store |
| `MENTAT_LOG_PATH` | `~/.mentat/logs` | Agent log dirs (transcript, summary) |
| `MENTAT_AGENT` | minted on emit | Agent id |
| `MENTAT_SESSION` | same as agent | Legacy alias |
| `MENTAT_REPO` | from git / `unknown` | Repo name for log path |
| `MENTAT_SLUG` | `agent-<pid>` | Sidecar filename segment |

Log dir created with `mode=0o700` on first emit. Reject + stderr sidecar on: unknown event, missing required field, non-JSON payload.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Validation failure |
| 64 | CLI arg parse error / missing subcommand |
| 70 | Unhandled Python exception |

## Rules

- `EVENT_CATALOG` in `log.py` is single source of truth; no event emitted outside catalog.
- Naming follows ADR-0007: past-tense verbs, `resource.action` shape, sub-reasons in payload.
- `emit` appends to `mentat.db` via `store.record_emit` — no audit `*.jsonl` files.
- `list <agent-id> --format=jsonl` exports the wire envelope to stdout for grep.
- `validate` checks export-format JSONL files (forensics / migration).
- `prune` deletes agent log dirs older than `--before`.

## Constraints

- Harness transcript: `~/.mentat/logs/<repo>/<agent_id>/transcript.jsonl` (not in sqlite).
- `emit` returns non-zero on validation reject; terminal emits in callers may halt orchestration.
- No external dependencies; stdlib only.
