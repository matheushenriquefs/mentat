# ADR 0002: Holding branch + `/to-rebase` instead of dmux's Merge

Status: Accepted (locked)
Date: 2026-05-31

## Context

dmux ships a Merge action (`m` pane menu) that runs `git commit` and `git
merge` on the host. Our team repos install pre-commit *inside* the devcontainer
(via uv, container-only formatters). The hook script lands in
`.git/hooks/pre-commit`, but `.git/` is bind-mounted out of the container — so
the hook fires from the host shell, where its tools aren't installed, and every
host-side commit fails. Hard-to-reverse: it shapes the entire branch topology
and every command that commits.

## Decision

Don't use dmux's Merge. Instead:

- Planner pane holds `branch/<feature>` with no commits of its own.
- Each dmux worktree branches from `main`.
- The implementer agent runs `/to-rebase` at the end of its session to
  fast-forward the holding branch onto its tip.
- Because the holding branch has no commits beyond its merge-base, the rebase is
  fast-forward — no `git commit` fires, so no host-side pre-commit fires.
- Commits during work route through the container via `devcontainer-run`.

## Rejected alternatives

- **dmux's Merge action.** Host-side commit+merge fails under container-side
  pre-commit (the whole reason this ADR exists).
- **dmux's `pre_merge` hook.** Unused — Merge never fires, so the hook has
  nothing to gate.
- **Automatic worktree cleanup on merge.** Lost with Merge. `x` still tears down
  via `before_worktree_remove`; close manually after `/to-rebase`.
- **dmux's AI-generated commit messages.** Need OpenRouter; we use Claude
  subscription auth via `/caveman-commit` instead.
- **Manual rebase from the planner pane** (the original flow). `/to-rebase`
  lifts it into the agent session. `git -C $ROOT rebase` runs against the shared
  `.git/` without the agent checking out the holding branch (which would
  conflict with the planner's checkout). `git merge-base --is-ancestor` aborts
  if the holding branch has its own commits, rather than replaying them and
  firing host pre-commit.

## Consequences

`/to-rebase` is pure git, runs from the implementer pane. The planner pane
re-engages only for `git push` + `gh pr create`. Setup and skill docs reference
this ADR rather than re-explaining "no pre_merge hook" inline.
