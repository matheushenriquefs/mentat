---
name: mentat-git
description: >
  Git operations routed through the running devcontainer.
  Use to commit, fast-forward rebase onto the holding branch, or print a cumulative diff vs a base.
---

Container-routing git wrapper. Container required (ADR-0004) — auto-ups via `mentat-container up` if missing; exit 69 if bring-up fails. Rebase is fast-forward-only — no replay across pre-commit. Diff honors `~/.mentat/config.jsonc` `diff_tool` if set.

## How to invoke

```
python3 ~/.agents/skills/mentat-git/scripts/git.py commit [-- <git commit args>]
python3 ~/.agents/skills/mentat-git/scripts/git.py rebase <holding-branch>
python3 ~/.agents/skills/mentat-git/scripts/git.py diff [<base>]
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

## Diff flow

1. Resolve base: arg → `main` (default).
2. Compute base SHA via `git merge-base <base> HEAD`.
3. Print stat + full diff `base..HEAD`. Honor `diff_tool` from `~/.mentat/config.jsonc` if set.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 69 | Container bring-up failed |
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
- Diff base defaults to `main`; override via positional arg.
- Stdlib-only script body; no PyYAML or other PyPI deps.

## Constraints

- Devcontainer must be reachable for the current worktree's git root.
- Holding-branch checkout location resolved from main worktree, not the calling worktree (worktree dirs cannot share a branch).
- `diff_tool` is optional; absent → vanilla `git diff`.
