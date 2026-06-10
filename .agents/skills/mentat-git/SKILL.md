---
name: mentat-git
description: >
  Git operations routed through the devcontainer when present.
  Use for commits, fast-forward rebases onto the holding branch, and cumulative diffs.
metadata:
  version: "0.1.0"
---

Container-routing git wrapper. Commit routes through the devcontainer if one is running for the current worktree; falls back to host if not. Rebase enforces fast-forward only. Diff reads `~/.mentat/config.jsonc` for an optional `diff_tool`.

## How to invoke

```
python3 ~/.agents/skills/mentat-git/scripts/git.py commit [<git args>]
python3 ~/.agents/skills/mentat-git/scripts/git.py rebase
python3 ~/.agents/skills/mentat-git/scripts/git.py diff
```
