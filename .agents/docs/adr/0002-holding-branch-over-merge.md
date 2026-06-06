# ADR 0002: Holding branch + `/mentat-rebase` over plain merge

Status: Accepted (locked)
Date: 2026-05-31

## Context

Team repos install pre-commit *inside* the devcontainer (via uv, container-only
formatters). The hook script lands in `.git/hooks/pre-commit`, but `.git/` is
bind-mounted out of the container — so the hook fires from the host shell, where
its tools aren't installed, and every host-side commit fails. Hard-to-reverse: it
shapes the entire branch topology and every command that commits.

## Decision

Use plain `git worktree` + ff-only rebase instead of host-side `git merge`:

- Planner session holds `branch/<feature>` with no commits of its own.
- Each agent worktree branches from `main`.
- The implementer agent runs `/mentat-rebase` at the end of its session to
  fast-forward the holding branch onto its tip.
- Because the holding branch has no commits beyond its merge-base, the rebase is
  fast-forward — no `git commit` fires, so no host-side pre-commit fires.
- Commits during work route through the container via `mentat-container-run`.

## Rejected alternatives

- **Host-side `git merge`.** Host-side commit+merge fails under container-side
  pre-commit (the whole reason this ADR exists).
- **Manual rebase from the planner pane** (the original flow). `/mentat-rebase`
  lifts it into the agent session. `git -C $ROOT rebase` runs against the shared
  `.git/` without the agent checking out the holding branch (which would
  conflict with the planner's checkout). `git merge-base --is-ancestor` aborts
  if the holding branch has its own commits, rather than replaying them and
  firing host pre-commit.

## Consequences

`/mentat-rebase` is pure git, runs from the implementer session. The planner session
re-engages only for `git push` + `gh pr create`. Setup and skill docs reference
this ADR rather than re-explaining the host pre-commit constraint inline.
