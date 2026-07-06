# ADR 0020: Test craft

Status: Accepted
Date: 2026-07-06

## Context

Mentat's test suite grew faster than its conventions. Some tests mock the audit
store and only prove a mock was called; others bundle unrelated assertions in one
function; warnings are swallowed by default. ADR-0014 set coverage floors but not
how to write tests that earn the lines they cover. Vertical slices need a shared
fixture layer so emit paths are exercised against real SQLite, not doubles.

## Decision

**Tests mirror source.** One test module per source submodule:
`test_<module>.py` follows `<module>.py`. No god-test-file spanning unrelated
concepts — the same criterion as ADR-0019 for source layout.

**Real dependency, not mock.** Prefer the real module, real SQLite, real git
worktree, and real subprocess when the cost is bounded. A mock is a last resort,
not the default.

**Fake only at model + subprocess seams.** The two allowed fake boundaries are
(1) the harness model adapter when no CLI is installed, and (2) subprocess spawn
when the test asserts the wire protocol, not the child process behavior.
Everything else — store, config, gates, emit — uses real code paths.

**One behavior per test.** Each test function proves one invariant. Setup is
shared via fixtures; assertions are not stacked across unrelated outcomes.

**ROI hierarchy.** Write tests in this order: (1) invariant/grep gates that
prevent regression of ADRs and env contracts, (2) unit tests on pure logic, (3)
journey/e2e tests for cross-module flows. Do not add e2e coverage for logic a
unit test already pins.

**`filterwarnings = error`.** Pytest treats every warning as a failure unless
narrowly ignored with reason at the call site. Silent warning debt is not
allowed.

**`real_audit_store` fixture.** `tests/conftest.py` provides a temp SQLite DB
and real `store.record_emit` / `mentat-log emit` path so verticals assert
events land in the store, not that a mock was called.

## Consequences

- Mock-heavy audit tests are replaced by store round-trips through the fixture.
- New tests follow mirror layout; reviewers reject god-files and stacked asserts.
- Warning fixes are forced at introduction time instead of accumulating.
