---
name: mentat-container
description: >
  Manage the devcontainer lifecycle for a mentat worktree.
  Use when you need to start, stop, run commands inside, or diagnose a devcontainer.
---

Start, stop, exec inside, and diagnose devcontainers for mentat worktrees. Wraps `devcontainer` CLI + Docker with worktree-aware slug derivation and atomic `override`.

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

- `up` synthesizes `.devcontainer/devcontainer.json` atomically if absent (compose or Dockerfile auto-detected). If a `devcontainer.json` already exists, `up` normalizes `name`, `workspaceFolder`, `workspaceMount`, `postCreateCommand`, `onCreateCommand`, and `mounts` in place when the workspace folder drifts from `/workspaces/<slug>` or the git mount is missing.
- `up` is idempotent: calling it twice is safe, returns exit 0 if already running.
- `down` stops and removes the container (`docker rm -f`) — never touches branch state. Container respawns on the next `up`.
- `run` requires container already up; fails fast with exit 2 if not running.
- `override` auto-detects `docker-compose.yml` or `Dockerfile` in worktree root; a sidecar-only compose gets a generated `mentat-dev` service layered on (see below).
- Atomic write for `.devcontainer/devcontainer.json`: writes to `.tmp` then renames.
- Slug = `basename(git rev-parse --show-toplevel)`.
- `workspaceFolder` is normalized to `/workspaces/<slug>` on the write path; read from existing `devcontainer.json` at run/exec time.
- `doctor` walks rules and prints human-readable status for each.
- ADR-0004: project tools execute inside the container by default; callers must not bypass `container.py`. `runtime = "host"` (see below) is the only supported opt-out and is config-driven, not a caller decision.

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

## Sidecar-only compose (generated dev service)

Some repos ship a `docker-compose.yml` only to run 3rd-party sidecars (a database, a
cache, a private Nitter) while the app itself runs outside compose. Detection then finds
**no** service that builds or mounts the source tree (`SidecarOnlyCompose`). Rather than
mis-pick a sidecar as the workspace, `up` synthesizes a dev service and merges it onto the
project compose via multi-file compose:

- `devcontainer.json` lists `dockerComposeFile: ["../docker-compose.yml", "mentat-dev.compose.yml"]`
  and sets `service: mentat-dev`. The overlay (`.devcontainer/mentat-dev.compose.yml`) is
  written by `container.py`; `override.synth_spec` stays pure and hands it back as text.
- The two files merge into **one** compose project, so the dev service joins the project's
  default network automatically — no explicit `networks:` block. The agent runs containerized
  and the ADR-0004 mantra holds (nothing on the host).

**Implication for app code:** inside the dev service, sidecars resolve by **service name**,
not `localhost`. Code that reached a sidecar at `localhost:8080` on the host must use
`nitter:8080` (the service name) in the container. mentat documents this; it does not rewrite
your app's `localhost` references.

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
- `devcontainer.json` synthesized when absent; normalized in place (name, workspaceFolder, mounts, postCreateCommand) when present but drifted from the expected slug-derived layout.
- Arch mismatch emits a warning via `doctor`; it does not exit non-zero.
