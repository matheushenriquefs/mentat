# ADR 0007: Audit envelope (renumbered from ADR-0009)

Status: Accepted (locked)
Date: 2026-06-06
Amended: 2026-06-09 (v2 — past-tense verbs; `~/.mentat/logs`; `EVENT_CATALOG` in Python)
Amended: 2026-06-10 (v3 — Stripe-style naming policy; reasons live in payload, not name)
Amended: 2026-06-11 (v4 — chunk.teardown added, 10 events)
Amended: 2026-06-12 (v5 — task.* + session.prune added, 16 events)
Amended: 2026-06-20 (v6 — F1: summary.md is one status-bearing file in the session log dir)
Amended: 2026-07-05 (v7 — SQLite canonical store; NDJSON export-only)

## Context

Mentat skills emit structured audit records so agents can be replayed, scored,
and pruned. Without a canonical schema records drift across agents, making log
rotation and tooling brittle. Shell-era surfaces (JSONC schema + `audit.sh` + pydantic
loader) replaced by a Python-only SSOT.

## Decision

**All audit events routed through `mentat-log emit`.** No skill writes audit rows directly.

**Canonical store:** `~/.mentat/mentat.db` (SQLite WAL, `lib/store.py`). The `event`
table is append-only truth; `agent`/`chunk`/`slice` are projections. Emit validates
against `EVENT_CATALOG`, then appends via `store.record_emit`.

**Wire envelope** (export shape for grep; `mentat-log list --format=jsonl`):

```
{ts, agent, session, event, payload}
```

- `ts`: ISO-8601 UTC.
- `agent`: emitting skill name (e.g. `mentat-orchestrate`).
- `session`: agent id (`$MENTAT_AGENT` / legacy `$MENTAT_SESSION`).
- `event`: past-tense verb (e.g. `plan.started`, `chunk.landed`).
- `payload`: JSON object — verdicts, scores, file:line refs only. Never raw diff.

**Transcript file:** `~/.mentat/logs/<repo>/<agent_id>/transcript.jsonl` — harness-owned,
append-only, not in sqlite.

**Stderr sidecar:** `<agent_log_dir>/.stderr/<skill>-<slug>.stderr` on emit reject.

**Summary file (F1):** `~/.mentat/logs/<repo>/<agent_id>/summary.md` — one status-bearing
file per agent. Frontmatter `status:` ∈ `{succeeded, failed, blocked, hitl-required}`.

**`EVENT_CATALOG`** lives in `.agents/skills/mentat-log/scripts/log.py` as
`dict[str, list[str]]` (event name → required fields). Stdlib only, no pydantic, no jsonc.

**16 canonical events:**
| Event | Required fields |
|---|---|
| `plan.started` | `path` |
| `plan.succeeded` | `path` |
| `plan.failed` | `path`, `reason` |
| `chunk.spawned` | `slug`, `plan`, `harness`, `worktree` |
| `chunk.landed` | `slug`, `sha`, `holding` |
| `chunk.ejected` | `slug`, `reason`, `where` |
| `chunk.teardown` | `slug`, `ok` |
| `gate.evaluated` | `gate`, `verdict`, `severity`, `message` |
| `review.submitted` | `reviewer`, `score`, `threshold`, `verdict` |
| `batch.reviewed` | `session`, `summary` |
| `task.created` | `id`, `slug` |
| `task.claimed` | `id`, `agent`, `expires_at` |
| `task.released` | `id` |
| `task.done` | `id` |
| `task.wontfix` | `id` |
| `session.prune` | `reclaimed_bytes` |

`chunk.ejected.reason` — see `lib.events.EJECT_REASONS`.

Log dir: `mode=0o700` on first write.

## Naming policy

Events follow Stripe webhook convention (https://docs.stripe.com/api/events/types):

- **Past-tense verbs.** `plan.started`, `chunk.landed`, `gate.evaluated`.
- **`resource.action` shape.** Subresources extend to `resource.subresource.action`.
- **Reasons live in payload, not name.**
- **New event name only when handler diverges.**

Catalog at 16 events; future growth still prefers payload extension over new names.

## Consequences

All bins subprocess to `mentat-log emit`. Schema changes: amend `EVENT_CATALOG`
in one file. Readers query SQLite (`mentat-log list`, `mentat-session track`,
`recover.attempt_count`, `diagnose`). NDJSON audit files are not stored; export
on stdout when a human greps. DDL and DAO rules: `.agents/rules/database.md`.
