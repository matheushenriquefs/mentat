---
name: mentat-container
description: >
  Manage the devcontainer lifecycle for a mentat worktree.
  Use when you need to start, stop, run commands inside, or diagnose a devcontainer.
metadata:
  version: "0.1.0"
---

Start, stop, exec inside, and diagnose devcontainers for mentat worktrees. Wraps `docker compose` with worktree-aware slug derivation and atomic compose-synth.

## How to invoke

```
python3 ~/.agents/skills/mentat-container/scripts/container.py <subcommand> <args>
```

Subcommands: `up`, `run`, `down`, `doctor`.
