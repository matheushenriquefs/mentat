# ADR 0014: Coverage gate

Status: Accepted
Date: 2026-07-01

## Context

Mentat's shipped Python surface (`.agents/lib`, `.agents/skills`) is the runtime
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

- **Unit — 100% testable-line.** The fast suite (`-m "not e2e"`) over the shipped
  runtime (`.agents/lib`, `.agents/skills`) must hit 100%. The floor lives in
  `pyproject.toml` (`[tool.coverage.report] fail_under = 100`). `tasks/` is dev
  tooling (the coverage runner itself, docs-sync, release) — out of the shipped
  surface and unable to self-measure, so it is not in the gated source; its
  behavior is still tested (`test_coverage_runner`). Entrypoints
  (`if __name__ == "__main__":`), `TYPE_CHECKING` blocks, `raise
  NotImplementedError`, and the stdlib-only `sys.path` bootstrap idiom are
  omit-listed via `exclude_also` — they carry no testable logic. Raw-tty I/O
  shells are covered by their extracted pure helpers, not by driving the terminal.
- **E2E — journey floor.** The `e2e`-marked journeys run over `.agents` with
  `--fail-under=45`, proving the real-subprocess / real-git paths stay wired. This
  caps well below the unit gate on purpose: e2e drives happy and realistic paths
  only, and large surfaces are not e2e-reachable from inside the devcontainer —
  Docker-in-Docker (`mentat-container`, compose), real-harness spawn (`implement`
  veto/checkpoint/teardown), worktree plumbing, and the lint/precommit gate
  toolchain. Those lines are the unit gate's job (already 100%). The e2e floor
  guards journey regression; it is not a second attempt at line coverage.

Both passes are chained in the `coverage` Taskfile task, so one `task coverage`
enforces both. The runner (`tasks/coverage.py`) takes `--fail-under=<n>` and
`--source=<paths>` so each pass sets its own floor and scope.

## Consequences

A dropped-below-floor branch fails `task coverage` and blocks the land, the same
way a red test does. Raising a threshold is a one-line config change plus the
backfill that earns it. New raw-tty or entrypoint code must factor its logic into
testable helpers rather than widen the omit-list — the omit-list is a fixed set of
idioms, not an escape hatch. The e2e floor sits far below the unit floor because
most of the runtime is not reachable through in-container journeys (see above); the
unit gate carries the line-coverage guarantee, and the e2e floor only ratchets
journey coverage so the real orchestrate-and-land paths cannot silently rot.
