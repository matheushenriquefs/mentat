# ADR 0007: Audit envelope (renumbered from ADR-0009)

Status: Accepted (locked)
Date: 2026-06-06
Amended: 2026-06-09 (v2 — past-tense verbs; `~/.mentat/logs`; `EVENT_CATALOG` in Python)
Amended: 2026-06-10 (v3 — Stripe-style naming policy; reasons live in payload, not name)

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

## Naming policy

Events follow Stripe webhook convention (https://docs.stripe.com/api/events/types):

- **Past-tense verbs.** `plan.started`, `chunk.landed`, `gate.evaluated`.
- **`resource.action` shape.** Subresources extend to `resource.subresource.action` (e.g., `chunk.dispute.created` if ever needed).
- **Reasons live in payload, not name.** `chunk.ejected{reason: "preflight"}` — never `chunk.ejected.preflight_failed`. Stripe emits `charge.failed` with `failure_code`; they do not emit `charge.failed.insufficient_funds`.
- **New event name only when handler diverges.** If consumers must wire a different `case`/`if` branch, justify a new name. Otherwise extend payload.

Industry corroboration: Sentry fingerprinting consolidates sub-reasons rather than splitting names; Datadog facets/tags carry sub-reasons over stable log sources; New Relic custom attributes attach to existing events.

Catalog stays at 9 events. Consumer skills extend via payload fields (e.g. `chunk.ejected.payload.logs_path` for doctor bundle), never via new event names.

## Consequences

`audit.sh`, `audit_schema.py`, `audit-schema.jsonc` deleted. All bins subprocess to
`mentat-log emit`. Schema changes: amend `EVENT_CATALOG` dict in one file. Old log
path `~/.agents/mentat/logs/` is stale; `mentat-install` reports it for cleanup.
