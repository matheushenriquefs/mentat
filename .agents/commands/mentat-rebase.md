---
description: Fast-forward the holding branch to this worktree's tip.
---

Holding branch: $ARGUMENTS

1. Emit start: `source ~/.agents/bin/lib/audit.sh && mentat_audit mentat-rebase rebase.start "{\"holding\":\"$ARGUMENTS\"}"`.
2. Verify fast-forward is safe: `git merge-base --is-ancestor $ARGUMENTS HEAD`. If it fails, emit `mentat_audit mentat-rebase rebase.conflict "{\"holding\":\"$ARGUMENTS\"}"` then abort — the holding branch has its own commits, replaying them would fire pre-commit on host.
3. Find the main repo root: `ROOT=$(dirname "$(git rev-parse --git-common-dir)")`.
4. Confirm the holding branch is checked out there: `git -C "$ROOT" branch --show-current` should equal `$ARGUMENTS`.
5. Fast-forward: `git -C "$ROOT" merge --ff-only "$(git rev-parse HEAD)"`.
6. Emit complete: `mentat_audit mentat-rebase rebase.complete "{\"holding\":\"$ARGUMENTS\"}"`.`
