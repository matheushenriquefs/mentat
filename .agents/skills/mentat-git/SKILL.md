---
name: mentat-git
description: >
  Git operations routed through the running devcontainer.
  Use to commit or fast-forward rebase onto the holding branch.
---

Container-routing git wrapper. Container required (ADR-0004) — auto-ups via `mentat-container up` if missing; exit 69 if bring-up fails. Rebase is fast-forward-only — no replay across pre-commit.

## How to invoke

```
python3 ~/.agents/skills/mentat-git/scripts/git.py commit [-- <git commit args>]
python3 ~/.agents/skills/mentat-git/scripts/git.py rebase <holding-branch>
python3 ~/.agents/skills/mentat-git/scripts/git.py worktree create <slug> [--base <branch>] [--parent <dir>]
python3 ~/.agents/skills/mentat-git/scripts/git.py worktree sweep [--force]
```

## Commit flow

1. Stage paths first; `commit` does not auto-stage.
2. Invoke `commit -- -m "<msg>"` for a one-line message; `-- -F <file>` for multi-line.
3. Container probe: missing → auto-up; second miss → exit 69.
4. Hook re-stage: pre-commit modifies tracked files → re-stage and re-invoke.
5. One commit per slice. Never squash.

Multi-line message via temp file:

```
printf '%s\n' "<message>" > .commit-msg
python3 ~/.agents/skills/mentat-git/scripts/git.py commit -- -F .commit-msg
rm .commit-msg
```

## Rebase flow

1. Verify `holding` is an ancestor of `HEAD` — fast-forward must be safe (replay would fire host-side pre-commit on the holding branch).
2. Resolve the main repo root from the current worktree.
3. Fast-forward the holding branch (checked out at the main root) to `HEAD`.
4. Non-FF condition → non-zero exit. Caller treats as `chunk.ejected{reason: rebase-conflicted}` per ADR-0007.

## Worktree create flow

1. Resolve main repo root via `git rev-parse --git-common-dir`.
2. Default parent dir = `<repo>/.mentat/worktrees/`; override via `--parent`.
3. Target path = `<parent>/<slug>`. Branch name = `<slug>`. Base branch = `--base` (default `main`).
4. Idempotent: target already a registered worktree → exit 0, print path.
5. Path exists but unregistered → exit 65 (conflict; never overwrite).
6. Base branch missing → exit 66.
7. Else `git worktree add -b <slug> <target> <base>`; print resolved target path on success.
8. Runs on host — `git worktree add` writes to main repo's `.git/worktrees/`, which is not bind-mounted into the new slug's container.

## Worktree sweep flow

1. List registered worktrees outside `<repo>/.mentat/worktrees/` (parent-folder strays) plus any `prunable` entries. The main worktree and live managed worktrees are never listed.
2. Default is a dry-run: print the targets and exit. Does not auto-run — destructive removal is operator-confirmed.
3. `--force` removes each (`git worktree remove --force`) then `git worktree prune`, leaving `git worktree list` clean.
4. A target holding uncommitted work is preserved, never force-removed — same dirty-vs-clean safe default as managed teardown (`lib.worktrees`).

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 65 | Worktree path conflict (path exists, not a registered worktree) |
| 66 | Worktree base branch does not exist |
| 69 | Container bring-up failed |
| 70 | Unexpected git error (e.g. `worktree create` outside a repo) |
| non-zero (other) | Underlying `git` exit code (FF-conflict, pre-commit fail, etc.) |

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `MENTAT_DOCKER` | `docker` | Override docker binary (test isolation) |
| `MENTAT_LOG_PATH` | `~/.mentat/logs` | Inherited from `mentat-log` for audit emits |

## Rules

- Commit routes through the running devcontainer only — never the host (ADR-0004).
- Auto-up is opportunistic: invoked once, no retry loop.
- Rebase is FF-only; non-FF → caller's eject path, not a force-push.
- One commit per slice via this skill; squash forbidden.
- Stdlib-only script body; no PyYAML or other PyPI deps.

## Constraints

- Devcontainer must be reachable for the current worktree's git root.
- Holding-branch checkout location resolved from main worktree, not the calling worktree (worktree dirs cannot share a branch).
