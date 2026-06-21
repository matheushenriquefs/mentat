# Install Mentat

Task-oriented. This gets Mentat onto a machine and selects a harness. For the first
run after installing, see [getting-started](../tutorials/getting-started.md).

## Prerequisites

| Dependency | Version | Why |
|---|---|---|
| Python | 3.11+ | The bin layer is stdlib-only Python. |
| Container engine | Docker 24+ (daemon running) | Every project-tool invocation runs in a devcontainer. Mandatory — there is no host-only mode. |
| devcontainer CLI | latest | Brings the per-chunk container up. Install with `npm i -g @devcontainers/cli`. |
| git | 2.40+ | Worktree support is load-bearing. |
| OS | macOS or Linux | — |

The container engine is a hard dependency ([ADR-0002](../adr/0002-holding-branch-over-merge.md),
[ADR-0004](../adr/0004-parallel-orchestration.md)). Without it, Mentat refuses to run.
The development toolchain (`ruff`, `pyright`, `uv`, `pytest`) ships inside the
devcontainer image — no host installation of those is needed.

## Install

The installer is idempotent. It clones the source under `~/.local/share/mentat`,
then sets up `~/.mentat/` state directories, `~/.agents/` skill directories, and
per-harness symlinks for any detected harness.

```bash
# interactive
curl -fsSL https://raw.githubusercontent.com/matheushenriquefs/mentat/main/install.sh | bash

# skip confirmation prompts
curl -fsSL https://raw.githubusercontent.com/matheushenriquefs/mentat/main/install.sh | bash -s -- --yes

# preview only, no filesystem writes
curl -fsSL https://raw.githubusercontent.com/matheushenriquefs/mentat/main/install.sh | bash -s -- --dry-run
```

The installer flags map to the `mentat-install` skill:

| Flag | Effect |
|---|---|
| `--dry-run` | Preview only — no writes. |
| `--yes` / `-y` | Skip confirmation and companion prompts. |
| `--skip-companions` | Skip third-party companion install prompts. |
| `--no-color` | Plain output. |

## What the installer sets up

- `~/.mentat/` — runtime state: logs, config, and an ADR symlink.
- `~/.agents/skills/mentat-*` — the skill directories.
- Per-harness symlinks (for example `~/.claude/`, `~/.cursor/`) for each detected
  harness, so the skills resolve from inside that harness.
- A `~/.mentat/bin` entry on your `PATH` (it prompts before editing your shell rc).
- An end-of-run report of any **stale paths** from a previous layout, for you to
  remove by hand.

Re-run the installer any time — already-present paths are skipped, and newly
detected harnesses gain their symlinks.

## Select a harness

A harness is the headless agent CLI Mentat drives. Built-in adapters: `claude-code`
and `cursor`.

Set the default in `~/.mentat/config.toml`:

```toml
harness = "claude-code"
```

Override per run with the `--harness` flag:

```
/mentat-implement run --harness cursor my-plan
```

A repository can pin its own harness in `<repo-root>/.mentat/config.toml`, which
overrides the global file for that repository.

## Verify

From inside a git repository, with the container engine running:

```
/mentat-plan smoke-test
```

If the planner starts and writes `~/.agents/plans/smoke-test.md`, the install is
working. Delete the throwaway plan when done.

To add a third-party harness adapter without forking, see [the plugin API](../PLUGINS.md).
