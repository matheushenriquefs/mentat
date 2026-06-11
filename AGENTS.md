# Mentat — Agent Guidelines

Rules for agents working inside Mentat — the orchestration harness.

See [CONTEXT.md](CONTEXT.md) for the full glossary. See [docs/adr/README.md](docs/adr/README.md) for the ADR index. See [README.md](README.md) for the public overview.

> **Mentat is agnostic by design.** Surfaces it touches stay swappable along these axes:
> - **Multiplexer** — any pane manager, or none.
> - **Harness** — any agent CLI / IDE assistant; drop a module to add one.
> - **Model provider** — vendor and tier chosen per skill; no hardcoded SKUs.
> - **OS** — any POSIX. Windows out of scope.
> - **Arch** — any host arch; container resolves via `linux/$(uname -m)`.
> - **Container engine** — any rootful daemon speaking compose v2.
> - **Shell** — any POSIX shell; scripts call `python3` not the user's `$SHELL`.
> - **Editor** — honor `$EDITOR` when set; never assume one.
> - **Target-repo toolchain** — mentat names none. The container provides (ADR-0004).

**Context budget.** When your context fills past ~70%, proactively summarize your core instructions, slice state, and decisions-so-far into a smaller form before continuing.

## Critical Constraints

- **Devcontainer-only execution for target-repo work.** All target-repo commands run via `python3 ~/.agents/skills/mentat-container/scripts/container.py run '<cmd>'`. Never call project tools (linters, test runners, formatters, interpreters) on the host. (ADR-0004)
- **Never fabricate.** If a verification step fails or an ADR doesn't cover a case, say so. Don't invent citations or outcomes.
- **No secrets.** No API keys, tokens, or credentials in any file — not in comments, not in examples.
- **Mentat names no target-repo toolchain.** The driver and all Mentat files are agnostic — they do not reference specific languages, test frameworks, or build tools. Those live in the target repo's own docs (ADR-0004).
- **Agent prompts must be self-contained.** References at most 1 level deep. No plan/slice/round numbers, no parent-doc refs, no version history. Reader is a stranger with no project history. Use `mentat-context-reviewer` to audit.

## Workflow Rules

When editing prompt files in `.agents/`:

1. Read the relevant ADRs for the area you're touching (`docs/adr/`). System ADRs always; the target repo's `docs/adr/` when working there.
2. Run verification with `python3 ~/.agents/skills/mentat-container/scripts/container.py run '<test cmd>'` if the target repo has one.
3. Commit via the `mentat-git` skill (routes through devcontainer if one exists).

Until Mentat has release tags, promote harness changes to the user's global install:

```bash
cp -R .agents/ ~/.agents/
```

## Comments

Default: write no comments. Add one only when the *why* is non-obvious — a hidden constraint, subtle invariant, or workaround for a specific bug. Comment *why*, not *what*. No commented-out code. No TODO comments. One short line max.

## Style

Writing rules for skills, agents, and commands: see [docs/STYLE.md](docs/STYLE.md).

Naming convention: kebab-case with `mentat-` prefix for skills and commands. ADRs: `NNNN-kebab.md`. Worktree slugs: `mentat-<epoch>-<pid>`.

## Quality Gates

Every modified file passes its class checker before commit. Run: `lefthook run pre-commit --files $(git diff --name-only "$base")`. Gate thresholds and reviewer subagents: [ADR-0003](docs/adr/0003-scored-review-gate.md). Tier-1 linter (`lint.py`) enforces LOC budgets, banned words, and article-drop for agents on every commit.

## Audit

Every command emits start + complete events via `mentat-log emit`. Event catalog: [ADR-0007](docs/adr/0007-audit-envelope.md). Use `mentat-session track` for live monitoring.

## Ship Surface

`mentat-install` rsyncs `.agents/` to `~/.agents/`. Excluded: `evals/`, `plans/`, `.dmux/`, `.mentat/`.

## Platform Support

Mentat targets POSIX shells (bash 4+, zsh) on Linux + macOS. Windows is out of scope — relies on POSIX `rename(2)`, `ln` hardlink atomicity, and standard GNU/BSD coreutils.

## Attribution

When borrowing a concept from another repo, add an entry to `CREDITS.md` under `## Inspired by` citing the upstream URL, the upstream's GitHub repo description verbatim, and one sentence naming the specific primitive borrowed.

## See also

- [CONTEXT.md](CONTEXT.md) — glossary + ADR index + flagged ambiguities
- [docs/STYLE.md](docs/STYLE.md) — full writing rules
- [docs/adr/README.md](docs/adr/README.md) — ADR index
- [README.md](README.md) — public overview, quickstart
- [CREDITS.md](CREDITS.md) — credits + runtime tool dependencies
- [.agents/AGENTS.md](.agents/AGENTS.md) — system harness rules
