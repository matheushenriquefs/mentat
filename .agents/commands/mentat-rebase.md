---
description: Fast-forward the holding branch to this worktree's tip.
---

Holding branch: $ARGUMENTS

1. Verify fast-forward is safe: `git merge-base --is-ancestor $ARGUMENTS HEAD`. If it fails, abort — the holding branch has its own commits, replaying them would fire pre-commit on host.
2. Find the main repo root: `ROOT=$(dirname "$(git rev-parse --git-common-dir)")`.
3. Confirm the holding branch is checked out there: `git -C "$ROOT" branch --show-current` should equal `$ARGUMENTS`.
4. Fast-forward: `git -C "$ROOT" merge --ff-only "$(git rev-parse HEAD)"`.
