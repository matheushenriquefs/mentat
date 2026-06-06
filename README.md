# Mentat

> "Once men turned their thinking over to machines in the hope that this would set them free. But that only permitted other men with machines to enslave them."
> — *Dune*, Frank Herbert

Agents can work unattended *because* the harness keeps them honest — isolated chunks, deterministic gates, an anti-cheat blacklist.

A lean, agnostic **multi-harness orchestrator** for parallel coding agents.

See [CONTEXT.md](CONTEXT.md) for the full workflow narrative, glossary, and ADR index.

## Quickstart

```bash
# Bring up the devcontainer for a worktree
bin/mentat-container-up

# Run a command inside the container
bin/mentat-container-run '<test command>'

# Fan out planned slices onto a holding branch
bin/mentat-orchestrate branch/my-feature plan1.md plan2.md plan3.md

# Run quality gates on changed files
lefthook run pre-commit
```

## Requirements

- git
- jq
- Docker

No language toolchain on the host. Mentat declares no interpreter, formatter, linter, or test runner — those run inside the target repo's devcontainer.

## Development

Dev-only tools (not required for consumers):

| Tool | Used for |
|------|----------|
| [vendir](https://github.com/carvel-dev/vendir) | Declarative vendoring of upstream skills |
| [lefthook](https://github.com/evilmartians/lefthook) | Pre-commit quality gates in dev |
| [yq](https://github.com/mikefarah/yq) | Task md frontmatter mutation (mentat-tasks) |
| [ruff](https://github.com/astral-sh/ruff) | Python lint + format for evals/ |
| [pyright](https://github.com/microsoft/pyright) | Python type checking for evals/ |

## No-framework thesis

Bash + jq + prompts.

No SDK, no orchestration framework, no platform lock. The driver (`mentat-orchestrate`) is ~260 lines of shell. The gate logic is in reviewer prompt files. The harness abstraction (`mentat-track`, `bin/lib/harness/<name>.sh`) normalizes `cursor-agent` and `claude-code` stream-json — swapping harnesses is a config change, not a rewrite.

The constraint is Docker. Everything else is a text file.

## Install

```bash
# Install / update the harness into ~/.agents/ (syncs vendored upstreams first)
bin/mentat-install

# Skip upstream sync (offline install)
bin/mentat-install --offline

# Dry-run
bin/mentat-install --dry-run
```

## Vendored skills

Third-party skills are declared in [`vendir.yml`](vendir.yml) and pinned in `vendir.lock.yml`. The vendor tree (`.agents/skills/vendor/`) is gitignored — `bin/mentat-install` materializes it on install via `vendir sync`. Attributions are in [CREDITS.md](CREDITS.md); regenerate with `bin/mentat-update`.
