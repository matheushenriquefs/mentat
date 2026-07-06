# ADR 0007: Audit envelope (renumbered from ADR-0009)

Status: Accepted (locked)
Date: 2026-06-06
Amended: 2026-06-09 (v2 — past-tense verbs; `~/.mentat/logs`; `EVENT_CATALOG` in Python)
Amended: 2026-06-10 (v3 — Stripe-style naming policy; reasons live in payload, not name)
Amended: 2026-06-11 (v4 — chunk_teardown added)
Amended: 2026-06-12 (v5 — task lifecycle events added)
Amended: 2026-06-20 (v6 — F1: summary.md is one status-bearing file in the agent log dir)
Amended: 2026-07-05 (v7 — SQLite canonical store; NDJSON export-only)
Amended: 2026-07-06 (v8 — flat snake_case catalog; event kind column)
Amended: 2026-07-06 (v10 — wire field `session` → `agent_id`; term retired repo-wide)

## Context

Mentat skills emit structured audit records so agents can be replayed, scored,
and pruned. Without a canonical schema records drift across agents, making log
rotation and tooling brittle. Shell-era surfaces (JSONC schema + `audit.sh` + pydantic
loader) replaced by a Python-only SSOT.

## Decision

**All audit events routed through `mentat-log emit`.** No skill writes audit rows directly.

**Canonical store:** `~/.mentat/mentat.db` (SQLite WAL, `lib/store.py`). The `event`
table is append-only truth; `agent`/`chunk`/`slice` are projections. The kind
column on `event` stores the flat snake_case catalog name. Emit validates against `EVENT_CATALOG`,
then appends via `store.record_emit`.

**Wire envelope** (export shape for grep; `mentat-log list --format=jsonl`):

```
{ts, agent, agent_id, event, payload}
```

- `ts`: ISO-8601 UTC.
- `agent`: emitting skill name (e.g. `mentat-orchestrate`).
- `agent_id`: agent id (`$MENTAT_AGENT`).
- `event`: past-tense snake_case verb (e.g. `chunk_started`, `chunk_landed`).
- `payload`: JSON object — verdicts, scores, file:line refs only. Never raw diff.

**Transcript file:** `~/.mentat/logs/<repo>/<agent_id>/transcript.jsonl` — harness-owned,
append-only, not in sqlite.

**Stderr sidecar:** `<agent_log_dir>/.stderr/<skill>-<slug>.stderr` on emit reject.

**Summary file (F1):** `~/.mentat/logs/<repo>/<agent_id>/summary.md` — one status-bearing
file per agent. Frontmatter `status:` ∈ `{succeeded, failed, blocked, hitl-required}`.

**`EVENT_CATALOG`** lives in `.agents/skills/mentat-log/scripts/log.py` as
`dict[str, list[str]]` (event name → required fields). Stdlib only, no pydantic, no jsonc.

**Canonical events** (count and fields live only in `EVENT_CATALOG`):
| Event | Required fields |
|---|---|
| `slice_scheduled` | `slug` |
| `slice_blocked` | `slug`, `blocked_by` |
| `slice_skipped` | `slug`, `reason` |
| `agent_started` | `harness` |
| `agent_stopped` | `reason` |
| `agent_reaped` | `reclaimed_bytes` |
| `chunk_started` | `slug`, `plan`, `harness`, `worktree` |
| `chunk_landed` | `slug`, `sha`, `holding` |
| `chunk_ejected` | `slug`, `reason`, `where` |
| `chunk_teardown` | `slug`, `ok` |
| `gate_evaluated` | `gate`, `verdict`, `severity`, `message` |
| `review_submitted` | `reviewer`, `score`, `threshold`, `verdict` |
| `batch_reviewed` | `agent_id`, `summary` |
| `task_created` | `id`, `slug` |
| `task_claimed` | `id`, `agent`, `expires_at` |
| `task_released` | `id` |
| `task_resolved` | `id` |
| `task_canceled` | `id` |
| `test_writable_requested` | `slug`, `path` |

`chunk_ejected` payload field `reason` — see `lib.events.EJECT_REASONS`.

Log dir: `mode=0o700` on first write.

## Naming policy

- **Past-tense verbs.** `chunk_started`, `chunk_landed`, `gate_evaluated`.
- **Flat snake_case.** No dot-separated resource namespaces at the emit boundary.
- **Reasons live in payload, not name.**
- **New event name only when handler diverges.**

Future growth still prefers payload extension over new event names.

## Consequences

All bins subprocess to `mentat-log emit`. Schema changes: amend `EVENT_CATALOG`
in one file. Readers query SQLite (`mentat-log list`, `mentat-track`,
`recover.attempt_count`, `diagnose`). NDJSON audit files are not stored; export
on stdout when a human greps. DDL and DAO rules: `.agents/rules/database.md`.
