# ADR 0007: Audit envelope (renumbered from ADR-0009)

Status: Accepted (locked)
Date: 2026-06-06
Amended: 2026-06-09 (v2 — past-tense verbs; `~/.mentat/logs`; `EVENT_CATALOG` in Python)

## Context

Mentat skills emit structured audit records so sessions can be replayed, scored,
and pruned. Without a canonical schema records drift across agents, making log
rotation and tooling brittle. Shell-era surfaces (JSONC schema + `audit.sh` + pydantic
loader) replaced by a Python-only SSOT.

## Decision

**All audit events routed through `mentat-log emit`.** No skill writes JSONL directly.

Envelope schema (JSONL, one row per event):
```
{ts, agent, session, event, payload}
```
- `ts`: ISO-8601 UTC (`datetime.now(UTC).isoformat()`).
- `agent`: agent slug (e.g. `mentat-orchestrate`).
- `session`: `$MENTAT_SESSION` (`<epoch>-<pid>`).
- `event`: past-tense verb (e.g. `plan.started`, `chunk.landed`).
- `payload`: JSON object — verdicts, scores, file:line refs only. Never raw diff.

**Log path:** `~/.mentat/logs/<repo>/<session>/<agent>-<slug>.jsonl`  
**Stderr sidecar:** `<base>/.stderr/<agent>-<slug>.stderr`

**`EVENT_CATALOG`** lives in `.agents/skills/mentat-log/scripts/log.py` as
`dict[str, list[str]]` (event name → required fields). Stdlib only, no pydantic, no jsonc.

**9 canonical events:**
| Event | Required fields |
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

`chunk.ejected.reason ∈ {implement-failed, gate-failed, rebase-conflicted, not-ff, hitl-required}`

Log dir: `mode=0o700` on first write.

## Consequences

`audit.sh`, `audit_schema.py`, `audit-schema.jsonc` deleted. All bins subprocess to
`mentat-log emit`. Schema changes: amend `EVENT_CATALOG` dict in one file. Old log
path `~/.agents/mentat/logs/` is stale; `mentat-install` reports it for cleanup.
