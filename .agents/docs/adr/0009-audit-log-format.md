# ADR-0009 — Audit Log Format

**Decided:** 2026-06-06
**Author:** matheussantosh

## Context

Mentat reviewers and the orchestrator emit structured audit records so sessions can be replayed, scored, and pruned. Without a canonical schema these records drift across agents, making log rotation (`mentat-logs-prune`) and tooling brittle.

## Decision

All audit events must be written via `mentat_audit()` in `bin/lib/audit.sh` using the JSONL schema:

```
{ts, agent, session, event, payload}
```

- `ts`: ISO-8601 UTC timestamp (jq `now|todate`).
- `agent`: agent slug (e.g. `mentat-bug-reviewer`).
- `session`: `$MENTAT_SESSION` (`<epoch>-<pid>`).
- `event`: verb string (e.g. `review.complete`, `gate.veto`).
- `payload`: JSON object — verdicts, scores, file:line refs only. Never raw diff or file content.

Log path: `$MENTAT_LOG_DIR/<repo>/<session>/<agent>-<slug>.jsonl`

Default `MENTAT_LOG_DIR`: `$HOME/.agents/mentat/logs` (user-global, never repo-local).

Rotation is handled by `mentat-logs-prune` (gzip >30 d, archive >90 d, delete >180 d).

## Consequences

- All agents source `audit.sh` and call `mentat_audit` — never `echo`/`printf` ad-hoc JSON.
- Payload validation (`jq -c`): invalid JSON falls back to `null` rather than crashing.
- Log dir is `chmod 700` on first write.
- `mentat-orchestrate` must export `MENTAT_REPO` and `MENTAT_SESSION` before sourcing sub-agents.
