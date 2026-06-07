# ADR-0010 — HITL Routing (AFK Seam Contract)

**Decided:** 2026-06-07
**Status:** Accepted
**Author:** matheussantosh
**Extends:** ADR-0003 (scored review gate), ADR-0006 (soft-readonly tests), ADR-0011 (orchestrate decomposition)
**Slot:** Reserved at the 0009→0011 numbering gap; forward-referenced by ADR-0012 before this file existed.

## Context

C3 from the G3 plan: AFK ("away-from-keyboard") was prose, not interface. Logs show 32 `AskUserQuestion` permission_denials in two days. The wedge pattern: an agent inside an AFK chunk hits ambiguity → calls `AskUserQuestion` → hook denies → agent self-answers as plain text → exits "completed" with no real work → `mentat-land-queue` reads `implement-fail`. Same shape, recurring.

AFK is a chunk-level property declared in the plan frontmatter (`class: AFK` vs `class: HITL`). It must propagate from `mentat-implement`/`mentat-orchestrate` down to the harness adapter invocation without leaking through globals, and the harness adapter must consume it deterministically.

ADR-0012 codified the per-harness capability table. G3-S2 wrote 8 rows; `supports_afk: true` on `claude-code` + `cursor`. ADR-0012 forward-referenced *this* ADR (`AFK contract from G3-S3`) before it existed — that gap is now closed.

This ADR locks the four-tuple contract that ADR-0012's `supports_afk` field claims compliance with.

## Decision

The AFK seam is a **four-tuple**: signal, exit code, audit reason, system-prompt clause.

### 1. Signal — env var `MENTAT_INTERACTIVE=0`

`mentat-implement` and `mentat-orchestrate` export `MENTAT_INTERACTIVE=0` into the chunk environment when the plan frontmatter declares `class: AFK`. Harness adapters in `.agents/bin/lib/harness/<name>.sh` read this env var to decide whether to enforce AFK behavior.

**Why env, not arg flag.** The signal must survive sub-invocations. Adapter shells (`claude-code.sh`) `exec` the real CLI (`claude -p`), which spawns subshells, which may shell out to `bash -lc '...'` inside container-run wrappers. An arg flag would have to be re-plumbed at every layer; an env var propagates by default. Same rationale as `MENTAT_SESSION` / `MENTAT_WORKTREE`.

The interactive default is `MENTAT_INTERACTIVE=1` (or unset → treated as 1). AFK is opt-in via explicit `=0`.

### 2. HITL exit code — `42`

A harness adapter that detects ambiguity in an AFK chunk exits with code `42`. Distinct from every other code in the system:

| Code | Source | Meaning |
|---|---|---|
| `0` | `mentat-orchestrate`, `mentat-land-queue` | success |
| `1` | `mentat-orchestrate` | general fail (per ADR-0011: partial) |
| `2` | `mentat-orchestrate`, `mentat-land-queue` (`die`) | tool-level error (per ADR-0011: `>=2`) |
| `42` | harness adapter (this ADR) | HITL — adapter refused to guess |

**Collision audit.** Greps over `.agents/bin/lib/harness/*.sh` show **no `exit N` / `return N` statements in any of the 8 adapters** — they delegate exit propagation to the underlying CLI. Greps over `mentat-orchestrate` and `mentat-land-queue` show `0`, `1`, `2` as the full inventory. Code `42` is collision-free.

The choice of `42` (rather than `3` or `255`) avoids the historical convention that `>= 64` is reserved (`sysexits.h`) while staying well clear of the in-use range.

### 3. HITL audit reason — `hitl-ambiguity`

When an adapter exits `42`, `mentat-land-queue` (G3-S8) emits a `land.complete` audit row with `{outcome: "eject", reason: "hitl-ambiguity"}` — **not** `implement-fail`. The reason field is the typed `reason` slot already defined by G1-S1's audit-schema.jsonc, so no schema change is required.

Kebab-lowercase per audit-schema convention.

### 4. System prompt clause (verbatim)

```
AFK mode: do not ask the user questions. On ambiguity, exit nonzero with a HITL audit reason instead of guessing.
```

This is the **canonical text**. It already appears verbatim in `harness-registry.jsonc` under the `system_prompt_template` field for `claude-code` and `cursor`. G3-S4/S5/S6 wire the adapters to prepend it to the user prompt when `MENTAT_INTERACTIVE=0`.

The clause is plain English on purpose: the recipient is the LLM inside the adapter, and the LLM's behavior is shaped by the prompt, not by ceremony.

## Axis discipline — three orthogonal mechanisms

A HITL exit is **not** a blacklist hit and **not** a scored-review failure. Future reviewers and tooling MUST NOT collapse them — they are different axes catching different failures.

| Axis | Mechanism | Failure mode | Owned by |
|---|---|---|---|
| **HITL** | exit `42` + `hitl-ambiguity` audit reason | adapter refused to guess at ambiguity | **ADR-0010** (this doc) |
| **Reward-hacking blacklist** | LLM-judge score `0.0` (veto) | agent gamed tests / weakened assertions | ADR-0006 (and ADR-0003 §blacklist) |
| **Scored-review veto** | reviewer score below threshold (plan/test ≥ 0.88) | plan misalignment / weak test asserts | ADR-0003 |

The blacklist axis is a *reviewer score* (0.0–1.0 over the diff), not a process exit code. The scored-review axis is a *reviewer threshold*. The HITL axis is a *process exit code + audit reason*. None of the three substitutes for another.

G3-S10 amends ADR-0003 and ADR-0006 to back-reference this distinction so the three-way map is anchored in all three docs.

## Cross-references

- **ADR-0012** — registry's `supports_afk` field declares which adapters honor this contract. ADR-0012 forward-referenced this ADR; the loop is now closed.
- **ADR-0011** — exit code semantics (`1`=partial, `>=2`=tool-level). This ADR extends the inventory with `42`.
- **G3-S4** — wires `lib/harness/claude-code.sh` to append `--disallowedTools AskUserQuestion` and prepend the clause when `MENTAT_INTERACTIVE=0`.
- **G3-S5** — `claude-code.sh` parses session JSONL for self-answered-question pattern, exits `42` on match.
- **G3-S6** — mirrors S4+S5 enforcement in `lib/harness/cursor.sh`.
- **G3-S7** — `.agents/commands/mentat-implement.md` references this contract by env var name + exit code.
- **G3-S8** — `mentat-land-queue` maps exit `42` → `{outcome: "eject", reason: "hitl-ambiguity"}`.
- **G3-S9** — `mentat-doctor` distinguishes `hitl-ambiguity` verdict (output names the suspect, not generic placeholder).
- **G3-S10** — amends ADR-0003 + ADR-0006 with the three-way axis cross-references.

## Consequences

- AFK becomes an interface (env + exit + reason + clause), not prose. Operators can reason about it; tooling can route on it.
- The 32 logged wedge sessions will, post G3-S5/S8, surface as `hitl-ambiguity` ejects instead of `implement-fail`. The land-queue learns to leave those worktrees up for operator review rather than collapsing them into the failure bucket.
- New adapters opt in via `supports_afk: true` in `harness-registry.jsonc`. Opt-out is fail-safe — an adapter with `supports_afk: false` simply never enforces AFK, leaving interactive runs unchanged.
- A typo at the env-var name fails closed: an unrecognized env value (`MENTAT_INTERACTIVE=maybe`) is treated as interactive (the default), so AFK is never silently engaged.
- The axis-discipline table makes ADR-0006 (blacklist) and ADR-0003 (scored veto) non-substitutable for HITL — a clean code read cannot buy back a HITL exit, and a HITL exit does not trigger blacklist removal.
