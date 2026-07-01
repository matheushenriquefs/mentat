# ADR 0014: Coverage gate

Status: Accepted
Date: 2026-07-01

## Context

Mentat's Python surface (`.agents/lib`, `.agents/skills`, `tasks`) is the runtime
that drives unattended AFK batches. Untested branches there fail silently in the
field — a wrong-branch rebase, an unhandled subprocess exit, a mis-parsed event —
where no human is watching. The scored review gate (ADR-0003) judges intent and
smells; it does not measure whether the code is *exercised*. A separate,
deterministic floor is needed, and it has to distinguish two kinds of confidence:
fast unit tests that pin every testable line, and real-subprocess / real-git
end-to-end journeys that prove the orchestrate-and-land surface actually works.

## Decision

Coverage is a blocking gate, run by `task coverage`, with two branch-coverage
passes:

- **Unit — 100% testable-line.** The fast suite (`-m "not e2e"`) over
  `.agents/lib`, `.agents/skills`, and `tasks` must hit 100%. The floor lives in
  `pyproject.toml` (`[tool.coverage.report] fail_under = 100`). Entrypoints
  (`if __name__ == "__main__":`), `TYPE_CHECKING` blocks, `raise
  NotImplementedError`, and the stdlib-only `sys.path` bootstrap idiom are
  omit-listed via `exclude_also` — they carry no testable logic. Raw-tty I/O
  shells are covered by their extracted pure helpers, not by driving the terminal.
- **E2E — 99%.** The `e2e`-marked journeys run over `.agents` with
  `--fail-under=99`, proving the real-subprocess / real-git paths stay wired.

Both passes are chained in the `coverage` Taskfile task, so one `task coverage`
enforces both. The runner (`tasks/coverage.py`) takes `--fail-under=<n>` and
`--source=<paths>` so each pass sets its own floor and scope.

## Consequences

A dropped-below-floor branch fails `task coverage` and blocks the land, the same
way a red test does. Raising a threshold is a one-line config change plus the
backfill that earns it. New raw-tty or entrypoint code must factor its logic into
testable helpers rather than widen the omit-list — the omit-list is a fixed set of
idioms, not an escape hatch. The e2e floor sits at 99, not 100, because a thin
margin of genuinely e2e-only-reachable error paths is acceptable slack; the unit
floor carries no such slack.
