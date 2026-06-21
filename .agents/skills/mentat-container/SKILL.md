---
name: mentat-container
description: >
  Manage the devcontainer lifecycle for a mentat worktree.
  Use when you need to start, stop, run commands inside, or diagnose a devcontainer.
---

Start, stop, exec inside, and diagnose devcontainers for mentat worktrees. Wraps `devcontainer` CLI + Docker with worktree-aware slug derivation and atomic `compose_render`.

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

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Command inside container exited non-zero |
| 2 | Container not running (for `run`) |
| 64 | CLI arg parse error / unknown subcommand |
| 69 | Docker daemon unreachable (`EX_UNAVAILABLE`) |
| 70 | Unhandled Python exception |

## Rules

- `up` synthesizes `.devcontainer/devcontainer.json` atomically if absent (compose or Dockerfile auto-detected).
- `up` is idempotent: calling it twice is safe, returns exit 0 if already running.
- `down` stops the container only — never touches branch state. Container respawns on the next `up`.
- `run` requires container already up; fails fast with exit 2 if not running.
- `compose_render` auto-detects `docker-compose.yml` or `Dockerfile` in worktree root.
- Atomic write for `.devcontainer/devcontainer.json`: writes to `.tmp` then renames.
- Slug = `basename(git rev-parse --show-toplevel)`.
- `workspaceFolder` read from `devcontainer.json`, not slug-derived.
- `doctor` walks rules and prints human-readable status for each.
- ADR-0004: project tools execute inside the container; host execution is forbidden by callers (e.g. `mentat-git`).

## Arch handling

Host arch (`uname -m`) and image platform are checked at `up` time. When host is
`arm64` and image is `linux/amd64` (or vice versa), `up` emits a visible warning about
emulation overhead before proceeding. No blocking — emulation is slow but functional.

Synthesized `devcontainer.json` (Dockerfile path) pins `runArgs: ["--platform", "linux/<arch>"]`
to the host: `platform.machine()` is mapped — `arm64`/`aarch64` → `linux/arm64`,
`x86_64`/`amd64` → `linux/amd64`. Unknown machines: `runArgs` omitted, Docker default.
`MENTAT_PLATFORM` env var overrides (e.g. `MENTAT_PLATFORM=linux/amd64` forces amd64 on arm64 host).

The `compose.yml.tmpl` branch substitutes the same arch value into the user template's `$arch`.
Static `docker-compose.yml` is user-owned and untouched — pin `platform:` there yourself if needed.

## Runtime: host opt-out (ADR-0004 forfeit)

`runtime` in config (`~/.mentat/config.toml`, repo overlay wins) selects the execution
target. Default (`docker`/`container`/unset) is the containerized path. Setting
`runtime = "host"` is an explicit, unsafe opt-out for a repo that genuinely cannot
containerize:

- `up` brings nothing up (returns 0); `run '<cmd>'` executes `<cmd>` directly on the host.
- The first such call per worktree prints one loud warning that ADR-0004 isolation is
  forfeited (host toolchain may be unset/mismatched, worktree not sandboxed), then stays
  silent. Opt-in only — never the default.

## Constraints

- Container must be running before `run` (containerized runtime). No auto-start inside `run`.
- `runtime = "host"` skips the container entirely; tools run on the host (ADR-0004 forfeit).
- `MENTAT_DOCKER` env var overrides the `docker` binary path (test isolation only).
- `MENTAT_PLATFORM` env var overrides host-arch detection for synth.
- `devcontainer.json` written only when absent; never overwritten if present.
- Arch mismatch emits a warning via `doctor`; it does not exit non-zero.
