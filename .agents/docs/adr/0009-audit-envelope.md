# ADR-0009 — Audit Envelope

**Decided:** 2026-06-06
**Amended:** 2026-06-07 (G1-S12 — envelope contract codified)
**Author:** matheussantosh

## Context

Mentat reviewers and the orchestrator emit structured audit records so sessions can be replayed, scored, and pruned. Without a canonical schema these records drift across agents, making log rotation (`mentat-logs-prune`) and tooling brittle. The G1 audit-substrate revamp (S1–S4) consolidated three previously divergent surfaces — JSONC schema file, bash emit function, python loader — into a single source-of-truth envelope.

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

Log path: `$MENTAT_LOG_PATH/<repo>/<session>/<agent>-<slug>.jsonl`

A `<slug>.stdout` companion file holds raw harness output (opaque, not audit). Both files are written per chunk by `mentat-orchestrate` and rotated together by `mentat-logs-prune`.

Default `MENTAT_LOG_PATH`: `$HOME/.agents/mentat/logs` (user-global, never repo-local).

Rotation is handled by `mentat-logs-prune` (gzip >30 d `*.jsonl` + `*.stdout`, archive >90 d, delete >180 d).

### Envelope contract (G1-S12)

All audit writes route through `audit.sh::mentat_audit`. Subprocess stderr lands in `<base>/.stderr/<agent>-<slug>.stderr` — never in `.jsonl`. Schema lives in `.agents/bin/lib/audit-schema.jsonc` (single source-of-truth, consumed by bash + python).

Three surfaces, one envelope:

- **G1-S1 — schema source-of-truth.** `.agents/bin/lib/audit-schema.jsonc` enumerates every event verb, its required fields, and optional sidecar templates. Comments document field meaning + lifecycle. The JSONC file is the single source-of-truth for both runtimes: bash `audit.sh` strips `//` comments and reads via `jq`; python `.agents/lib/audit_schema.py` strips comments and `json.loads`-es the same file.

- **G1-S2 — emit fn.** `audit.sh::mentat_audit` is the only function that may append to `<base>/<agent>-<slug>.jsonl`. It loads the schema once (cached in `MENTAT_AUDIT_SCHEMA`), rejects unknown events / non-JSON payloads / missing required fields, and routes rejects to the stderr sidecar instead of polluting `.jsonl`. Callers may not write JSONL rows directly — every bin that emits audit data sources `audit.sh` and calls `mentat_audit`.

- **G1-S4 — stderr sidecar.** Subprocess stderr (final-review harness, gate runs, container-run failures) tees to `<base>/.stderr/<agent>-<slug>.stderr` via `_mentat_audit_sidecar`. The sidecar file is created lazily on first write. Raw stdout that needs auditing must be captured into a variable and emitted as a typed payload field — never appended to `.jsonl`.

This separation is load-bearing: stale-text in `.jsonl` breaks `jq -c '.'` parsing, breaks the python loader, breaks `mentat-doctor`, and breaks evals replay. The contract makes a bad emit observable (reject row in sidecar) instead of silent (corrupted `.jsonl`).

### Event verb registry

Payload schemas live in `.agents/bin/lib/audit-schema.jsonc` (canonical) and `.agents/lib/audit_schema.py` (pydantic loader). Canonical verbs:

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

New verbs must land in `audit-schema.jsonc` first (with required-field list + optional sidecar template) before any caller emits them. `mentat_audit` rejects unknown verbs.

## Consequences

- All bins source `audit.sh` and call `mentat_audit` — never `echo`/`printf` ad-hoc JSON, never raw `>>` to a `.jsonl` path.
- All commands (`mentat-plan`, `mentat-implement`, `mentat-rebase`, `mentat-eval`) emit start + complete via `source ~/.agents/bin/lib/audit.sh && mentat_audit`.
- Payload validation (`jq -c` in bash, pydantic in python): non-JSON or schema-violating payloads route to `<base>/.stderr/<agent>-<slug>.stderr` and the row is dropped — invalid rows never reach `.jsonl`.
- Schema changes are one-edit: amend `audit-schema.jsonc` once, both runtimes pick it up. No more dual-maintenance of bash arrays + python constants.
- Log dir is `chmod 700` on first write.
- `mentat-orchestrate` must export `MENTAT_REPO` and `MENTAT_SESSION` before sourcing sub-agents.
- `final-review.jsonl` path is retired — all orchestrate events go to `mentat-orchestrate-<session>.jsonl`.
- Verification (S12): `grep -r 'append.*\.jsonl' .agents/bin/` returns only `audit.sh` — no other bin appends to a `.jsonl` audit row.
