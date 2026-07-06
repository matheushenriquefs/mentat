---
paths:
  - "tests/**/*.py"
---

# Testing

ADR-0020 governs how mentat tests are written. These rules apply to every file
under `tests/`.

## Mirror source layout

- One test module per source submodule: `test_chunk.py` follows `chunk.py`.
- Do not add a god-test-file that asserts across unrelated concepts. Split when
  the source split exists or is planned in the same slice.

## Real dependency, not mock

- Prefer real SQLite (`store.connect`), real git worktrees, and real module
  imports. Use `real_audit_store` (conftest) for emit round-trips.
- Do not mock `store.record_emit`, `EventDAO.append`, or the audit catalog to
  prove an emit happened — assert the row landed in the store.
- Mocks are allowed only at the harness model adapter seam and subprocess spawn
  when the test pins the wire protocol, not child behavior.

## One behavior per test

- Each `test_*` function proves one invariant. Shared setup belongs in fixtures
  or helpers; do not stack unrelated assertions in one test.
- A grep-gate test (zero raw env reads, zero retired wire-term token) is one invariant —
  keep it in `test_foundation_*.py`, not scattered across journey files.

## ROI hierarchy

1. Invariant / grep gates (ADRs, env accessors, drift lint).
2. Unit tests on pure logic and DAOs.
3. Journey / e2e tests for cross-module flows.

Do not add e2e coverage for behavior a unit test already pins.

## Warnings

- Pytest runs with `filterwarnings = error`. Fix or narrowly ignore at the call
  site with an explicit reason — never broaden the global ignore list to green
  a suite.
