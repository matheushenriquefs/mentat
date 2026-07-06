# ADR 0016: Mutation signal — advisory, never a gate

Status: Accepted
Date: 2026-07-06

## Context

Line coverage proves a line *ran*; it cannot prove any assertion would *notice* that
line breaking. Once the unit floor dropped from 100% to 90%
([ADR-0014](./0014-coverage-gate.md) amendment), coverage clears on behavior tests,
but a covered line can still be asserted by nothing — the "covered-but-checks-nothing"
gap. Mock-heavy tests are the acute form: 100% coverage where a mock swallowed the
behavior tests the mock, not the code.

The consensus on what makes an assertion valuable is whether it would fail if a real
behavior broke — i.e. whether it kills a mutant (Fowler; Google SWE Book ch.12;
Khorikov). Just et al., *Are Mutants a Valid Substitute for Real Faults in Software
Testing?* (FSE 2014), show mutant-detection correlates with real-fault detection
**independently of code coverage** — a mutant that survives is signal that coverage
cannot give.

But mutation testing is expensive and only partly deterministic: timeout-killing is
load-dependent, and it inherits test-order flakiness. The FSE 2014 result validates
mutation for **test hardening**, not as an automated pass/fail on generated code.

## Decision

Mutation testing is an **advisory signal**, never a gate.

- **Tooling.** `mutmut` (3.x, pytest-native, incremental) at the dev layer
  ([ADR-0008](./0008-python-runtime.md)-safe: no runtime dependency). Config lives in
  `[tool.mutmut]` in `pyproject.toml` — `source_paths` matches the coverage gate's
  shipped-runtime surface, test order is pinned (`-p no:randomly`), and per-mutant
  time is bounded (`timeout_multiplier` / `timeout_constant`) so a run is reproducible.
  (`cosmic-ray` is the fallback if detection fidelity later outweighs ergonomics.)
- **Scope.** `task mutation` (`tasks/mutation.py --changed`) runs only on shipped-source
  files touched since the merge-base with `main`. The shipped-source set is read from
  `[tool.coverage.run] source`, so the surface the coverage gate omits is excluded
  here too. Output is a compact `file:line` list of surviving mutants.
- **Never in the gate or land re-gate path.** No scorer consumes it as a veto or a
  threshold. It is surfaced to `mentat-test-reviewer` as an *advisory* input:
  surviving mutants on changed lines flag a covered-but-asserts-nothing test, which the
  reviewer weighs against its primary question (would this test fail if a real bug were
  introduced?). The `surviving_mutants` field rides on the `ReviewVerdict` but does not
  affect the verdict.

## Consequences

- The mutation signal and the reviewer's mock-smell lens reinforce each other: a mutant
  that survives *because a mock swallowed it* is the exact failure the lens targets.
- A run is scoped and reproducible enough to be useful, but its cost and partial
  non-determinism keep it off the blocking path — a red mutation run never ejects a
  chunk. Hardening tests in response to survivors is the operator's call, not the gate's.
- Because it is advisory and dev-layer, `tasks/mutation.py` is out of the coverage gate
  (like the rest of `tasks/`); its deterministic core (changed-file scoping, key→
  location mapping, survivor parsing, report format) is unit-tested regardless.
