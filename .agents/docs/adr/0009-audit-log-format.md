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

A `<slug>.stdout` companion file holds raw harness output (opaque, not audit). Both files are written per chunk by `mentat-orchestrate` and rotated together by `mentat-logs-prune`.

Default `MENTAT_LOG_DIR`: `$HOME/.agents/mentat/logs` (user-global, never repo-local).

Rotation is handled by `mentat-logs-prune` (gzip >30 d `*.jsonl` + `*.stdout`, archive >90 d, delete >180 d).

### Event verb registry

Payload schemas live in `.agents/lib/audit_schema.py` (pydantic). Canonical verbs:

| Actor | Verbs |
|---|---|
| mentat-plan | `plan.start`, `plan.complete` |
| mentat-implement | `implement.start`, `implement.complete`, `implement.preflight` |
| mentat-rebase | `rebase.start`, `rebase.complete`, `rebase.conflict` |
| mentat-eval | `eval.start`, `eval.complete` |
| mentat-release | `release.start`, `release.complete` |
| mentat-orchestrate | `land.complete`, `review.final` |
| mentat-update | `sync.complete` |
| (any) | `rename.complete`, `staleref.sweep`, `review.dismiss` |

## Consequences

- All bins source `audit.sh` and call `mentat_audit` — never `echo`/`printf` ad-hoc JSON.
- All commands (`mentat-plan`, `mentat-implement`, `mentat-rebase`, `mentat-eval`) emit start + complete via `source ~/.agents/bin/lib/audit.sh && mentat_audit`.
- Payload validation (`jq -c`): invalid JSON falls back to `null` rather than crashing.
- Log dir is `chmod 700` on first write.
- `mentat-orchestrate` must export `MENTAT_REPO` and `MENTAT_SESSION` before sourcing sub-agents.
- `final-review.jsonl` path is retired — all orchestrate events go to `mentat-orchestrate-<session>.jsonl`.
