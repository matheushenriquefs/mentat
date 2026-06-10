# ADR 0002: Holding branch over merge

Status: Accepted (locked)
Date: 2026-05-31
Amended: 2026-06-09 (Python-era invocation: `mentat-git rebase`)

## Context

Team repos install pre-commit *inside* the devcontainer (container-only formatters
installed via uv). The hook lands in `.git/hooks/pre-commit`, but `.git/` is
bind-mounted out of the container — hook fires from the host shell where its tools
aren't installed, every host-side commit fails. Hard-to-reverse: shapes branch
topology and every command that commits.

## Decision

Use `git worktree` + ff-only rebase instead of host-side merge:

- Planner session holds `branch/<feature>` with no commits of its own.
- Each agent worktree branches from `main`.
- Implementer runs `mentat-git rebase` (Python, full path) at end of session to
  fast-forward the holding branch onto its tip.
- Holding branch has no commits beyond its merge-base → rebase is fast-forward →
  no `git commit` fires → no host-side pre-commit fires.
- Commits during work route through the container via `mentat-container run`.

Invocation:
```
python3 ~/.agents/skills/mentat-git/scripts/git.py rebase
```

## Rejected alternatives

- **Host-side `git merge`.** Fails under container-side pre-commit.
- **Manual rebase from the planner pane.** `mentat-git rebase` lifts it into the
  agent session. `git merge-base --is-ancestor` aborts if holding has own commits.

## Consequences

`mentat-git rebase` is pure git, runs from the implementer session. Planner
re-engages only for `git push` + `gh pr create`. Docs reference this ADR.
No `bin/mentat-rebase` shell script; Python skill handles routing.
