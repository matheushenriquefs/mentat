# ADR 0006: Soft read-only test enforcement — impl-contract + blacklist, driver agnostic

Status: Accepted (locked)
Date: 2026-06-04
Amended: 2026-06-09 (v2 — pytest semantics; trajectory blacklist enforced via `llm/test.md`)
Amended: 2026-06-10 (v3 — `llm/test.md` → `mentat-test-reviewer` subagent)

## Context

ImpossibleBench: make test files read-only during implementation and agent cheating
drops to near zero. ADR-0003's trajectory blacklist catches test-tampering after it
happens; read-only is the preventive version. Kernel-level read-only mount rejected
because it requires the driver to know which files are tests — breaking ADR-0004's
language/layout agnosticism.

## Decision

Enforcement in two layers, both agnostic:

**Soft preventive layer — `mentat-implement` contract.** During a TDD slice, once
the failing test is written, the agent works impl-only: it does not modify existing
test files until the slice is green. Rule, not kernel guarantee.

**Hard detective layer — trajectory blacklist (`mentat-test-reviewer`).** Reviewer subagent
reads agent's edit trajectory. Test-file write during impl phase, weakened assertion,
redirected runner → blacklisted move. Deterministic veto: score `0.0`.

Enforcement is test-runner-shaped:
1. Write failing test → commit.
2. Implement → `task test` green.
3. Gate pass → commit per slice.

HITL exit `42` (`hitl-ambiguity`) is NOT a blacklist hit — separate axis (ADR-0004).

Blacklist entries kept (nothing retired by soft prevention):
- Writing to test file during impl phase.
- Weakening/deleting an assertion.
- Redirecting test runner to a writable copy.
- Any move that produces green without genuine impl.

## Consequences

`mentat-implement` gains impl-only-after-red contract clause. `mentat-test-reviewer`
carries the trajectory blacklist. Driver and container scripts untouched — no test
path knowledge in the driver. ADR is index-only in AGENTS.md.
