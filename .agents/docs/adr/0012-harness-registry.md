# ADR-0012 — Harness Registry

**Decided:** 2026-06-07
**Status:** accepted
**Author:** matheussantosh
**Extends:** ADR-0004 (parallel-slicing orchestration), ADR-0010 (HITL routing)

## Context

Mentat fans out work across 8 shell harness adapters (`aider, amp, claude-code, codex, copilot, cursor, gemini, openhands`) — 141 LOC of duplicated shell glue under `.agents/bin/lib/harness/<name>.sh`. Each adapter re-derives invocation argv, output format, normalization fn, and AFK behavior. Two adapters touch AFK plumbing (`claude-code` + `cursor` — per G3-S5/S6); the other six have no real-world traffic (logs show `claude-code` dominant, `cursor` second).

The C7 audit ("worth exploring") identifies the 8 adapters as a real seam: AFK is currently doc-only, not enforced at the harness boundary. 32 `AskUserQuestion` permission_denials over two days trace to the seam being prose-not-interface. A registry consolidates per-harness capability claims so AFK plumbing has one declarative home.

G1-S1 codified a parallel pattern for audit telemetry (`audit-schema.jsonc` as single source-of-truth, bash + python both consume by stripping `//` comments). This ADR mirrors that pattern for harness capability rows.

## Decision

A JSONC registry at `.agents/bin/lib/harness-registry.jsonc` declares one row per harness adapter. The file is the single source-of-truth for harness capability claims, consumed by bash (`audit.sh`-style: strip `//` + `jq`) and python (strip `//` + `json.loads`). Adapters in `.agents/bin/lib/harness/<name>.sh` source the registry to derive their AFK behavior, disallowed-tools argv fragment, and system-prompt prefix — not to re-implement those decisions per-adapter.

### Registry path

`.agents/bin/lib/harness-registry.jsonc` — colocated with shell-side consumers (`audit.sh`, `harness/*.sh`). The Python reader (future `.agents/lib/harness_registry.py`) imports by absolute path, not module discovery. Rationale: the registry is single source-of-truth for two runtimes (bash + python), and the bin/lib home keeps it next to the consumers that read it most.

### Schema — one row per harness

Each row under `harnesses.<name>` carries six required fields:

| Field | Type | Purpose |
|---|---|---|
| `name` | string | Adapter slug; must equal the row key and the `lib/harness/<name>.sh` basename. |
| `bin` | string | Executable name on `$PATH` (e.g. `claude`, `cursor`, `aider`). |
| `base_args` | string[] | Argv array prepended to every invocation before the prompt. |
| `supports_afk` | bool | `true` iff this adapter enforces AFK contract from G3-S3 (env `MENTAT_INTERACTIVE=0` honored, HITL exit code emitted on ambiguity). Initially `true` only for `claude-code` + `cursor`. |
| `disallowed_tools_arg` | string | Template fragment appended to argv when `MENTAT_INTERACTIVE=0`. Empty string ⇒ adapter has no native disallow-tools knob; AFK enforcement falls back to system-prompt clause only. |
| `system_prompt_template` | string | Text prepended to the user prompt in AFK mode. The G3-S3 clause forbidding question-asking lives here. |

Field-list is closed: any additional fields are advisory-only and ignored by the loader. New required fields must be added in their own ADR amendment.

### Fail-closed policy for unknown harnesses

The registry top-level declares `"on_unknown": "refuse"`. When a caller invokes an adapter whose name is absent from `harnesses`, the loader must refuse to spawn and exit nonzero with the missing name. Fail-closed by contract — no implicit defaults, no silent fallback to a "generic" adapter. Rationale: harness capability claims (especially `supports_afk`) are load-bearing for the HITL routing in ADR-0010; an unknown harness has unknown AFK behavior, and pretending otherwise is the exact failure mode this ADR exists to prevent.

### Stub seeding (S1) vs row writing (S2)

G3-S1 lands the ADR and the empty stub. The stub declares `required_fields` and `on_unknown` at the JSONC root; the `harnesses` map is empty. G3-S2 writes the 8 rows. G3-S4/S5/S6 wire claude-code + cursor adapters to consume the registry. The seam is real because at least two adapters consume it — `supports_afk: true` rows are not aspirational.

### Cross-references

- **G3-S2** populates the 8 harness rows against this schema.
- **G3-S4** wires `claude-code.sh` to read `disallowed_tools_arg` + `system_prompt_template`.
- **G3-S5** consumes the same fields for ambiguity-exit detection.
- **G3-S6** mirrors enforcement in `cursor.sh`.
- **ADR-0010** owns the AFK/HITL plan-class boundary; this ADR owns the per-harness capability claim that the boundary depends on.

## Consequences

- Adapters become thin: invocation argv + normalization fn stay in `.sh`, but capability claims (AFK, disallowed-tools knob, system-prompt clause) migrate to the registry.
- New harness onboarding is a one-row edit to `harness-registry.jsonc` + a `.sh` file with the canonical fn names — no re-deciding the AFK contract per-adapter.
- Adding a required field is an ADR amendment, not a silent loader change.
- Fail-closed default means a typo in harness name fails at spawn time, not mid-run with cryptic behavior.
- Schema and contract evolve in lockstep: S1 declares both the ADR and the stub's `required_fields` array; tests cross-check the two so drift is caught at gate time.
