---
name: mentat-container
description: >
  Manage the devcontainer lifecycle for a mentat worktree.
  Use when you need to start, stop, run commands inside, or diagnose a devcontainer.
metadata:
  version: "0.1.0"
---

Start, stop, exec inside, and diagnose devcontainers for mentat worktrees. Wraps `devcontainer` CLI + Docker with worktree-aware slug derivation and atomic compose-synth.

## How to invoke

```
python3 ~/.agents/skills/mentat-container/scripts/container.py <subcommand> <args>
```

Subcommands: `up`, `run`, `down`, `doctor`.

## Subcommands

| Subcommand | Args | Description |
|---|---|---|
| `up` | — | Start devcontainer for cwd worktree (idempotent) |
| `run` | `'<cmd>'` | Exec command inside running container |
| `down` | — | Stop container |
| `doctor` | — | Walk container invariants and report issues |

## Examples

```sh
# Bring up container for this worktree
python3 ~/.agents/skills/mentat-container/scripts/container.py up

# Run a command inside
python3 ~/.agents/skills/mentat-container/scripts/container.py run 'uv run pytest'

# Stop it
python3 ~/.agents/skills/mentat-container/scripts/container.py down

# Diagnose
python3 ~/.agents/skills/mentat-container/scripts/container.py doctor
```

## Invariants

- `up` synthesizes `.devcontainer/devcontainer.json` atomically if absent (compose or Dockerfile auto-detected).
- `run` exits 99 if container not running.
- Slug = `basename(git rev-parse --show-toplevel)`.
- `workspaceFolder` read from `devcontainer.json` (not slug-derived) — G2-S9 invariant.
- `MENTAT_DOCKER` env override for testing without real Docker.
