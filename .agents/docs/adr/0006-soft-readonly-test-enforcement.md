# ADR 0006: Soft read-only tests — implement-contract + blacklist, driver agnostic

Status: Accepted (locked)
Date: 2026-06-04

## Context

ImpossibleBench's headline result: make test files read-only (or hidden) during
implementation and agent cheating drops to near zero — a model won't try to game a
target it can't edit. ADR 0003's trajectory blacklist catches the test-tampering
*move* after it happens; read-only is the *preventive* version. The report flagged
adding it as the single highest-value control.

The obvious implementation — mount the test files read-only in the devcontainer —
turns out to break the system's founding rule. Hard-to-reverse: it shapes
`/mentat-implement`'s contract and the `mentat-bug-reviewer` veto set, so it's locked here.

## The trap we rejected: a driver-built read-only mount

Mounting tests read-only requires *knowing which files are tests*. There is no
agnostic way for the driver or `mentat-container-up` to know that:

- Many projects have no single `tests/` dir. JS/TS routinely co-locate `foo.ts`
  with `foo.test.ts`, or scatter `__tests__/` through `src/`.
- A whole-dir read-only mount would freeze the impl files the agent must write.
- A file-level mount can't cover a test file that doesn't exist yet — and TDD
  slices create new test files mid-session.
- Globbing `*.test.*` / `*_test.*` / `test_*.py` to bind-mount each file is the
  driver acquiring language- and framework-specific layout knowledge. That is
  exactly the tool/model/platform/language agnosticism ADR 0004 forbids ("the
  driver names no project tool … agnostic by construction").

Co-located tests + TDD + a kernel mount is pick-two. We don't pick the mount.

## Decision — enforcement is the agent's, in two layers, both agnostic

The same pattern ADR 0004 already uses for re-gating (spawn an agent that reads the
repo's own CLAUDE.md/AGENTS.md and runs *that* project's gates — the driver names
no tool): the agent holds the project knowledge, the driver holds none.

- **Soft preventive layer — the `/mentat-implement` contract.** During a TDD slice,
  once the failing test is written, the agent works impl-only: it does not modify
  existing test files until the slice is green. The agent already knows which files
  are tests — it had to discover the test runner to run the loop at all. This is a
  *rule*, not a kernel guarantee: it reduces the agent's tendency to game (the
  ImpossibleBench effect) without the driver knowing a single test path.

- **Hard detective layer — the trajectory blacklist (ADR 0003).** The real gate
  stays where it is already agnostic and deterministic: `mentat-bug-reviewer` reads
  the agent's own edit/tool trajectory. A test-file write during the impl phase, a
  weakened assertion, a redirected runner — all surface as blacklisted *moves*
  regardless of language or layout, because the lens reads *what the agent did*,
  not *where the files live*.

Prevention is soft by design; enforcement is the blacklist. We do not pretend the
contract is airtight, so we do not weaken the blacklist on the strength of it.

## Consequence for the blacklist: keep everything, add one

Because there is no kernel mount, **nothing is "fully covered" by prevention** — so
no blacklist entry is retired. All ADR-0003 entries stay. One entry is ADDED, because
a soft "don't edit tests" rule creates a new incentive to fake green without touching
the test file:

- **NEW — runner redirection to a writable copy.** Pointing the test runner at a
  duplicated/relocated test tree, or setting config/env so tests resolve from a
  writable path, then editing those. Original tests look untouched; the green is
  fake. → blacklisted move.

See ADR 0003's amended blacklist set for the full list.

## Rejected alternatives

- **Kernel/bind read-only mount of test files.** Breaks agnosticism (above). The
  whole reason this ADR is shaped the way it is.
- **Mount only when a separate `tests/` dir exists; blacklist-only otherwise.**
  Two code paths for the same guarantee, and the "detect a test dir" half is still
  layout knowledge in the driver. Rejected for the same agnosticism reason.
- **Hiding test files instead of read-only.** TDD needs the agent to read and run
  the tests; hiding them defeats the loop. ImpossibleBench's "hide OR read-only" —
  we can use neither at the mount layer, hence the soft-contract substitute.
- **Treating the soft rule as sufficient (dropping blacklist test-write entries).**
  A rule is not enforcement. The blacklist is the gate; the rule only lowers the
  temptation. Considered (the "Hybrid" drop) and rejected once the mount fell.

## Consequences

`/mentat-implement` gains a one-line impl-only-after-red contract clause. `mentat-bug-reviewer`
gains the runner-redirection move and keeps all others. The driver and
`mentat-container-*` scripts are untouched — they never learn what a test file is. This
ADR is index-only in AGENTS.md (title only; body on demand — ADR 0001's budget).
Why the soft posture: ImpossibleBench is a frequency result, not an impossibility
proof — runner redirection and impl-only gaming survive any test-file lock, so the
detective blacklist remains load-bearing.
