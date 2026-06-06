# Mentat — Agent Guidelines

Rules for agents working inside Mentat — the orchestration harness.

See [CONTEXT.md](CONTEXT.md) for the full glossary and ADR index. See [STYLE.md](STYLE.md) for writing rules. See [README.md](README.md) for the public overview.

## Critical Constraints

- **Devcontainer-only execution for target-repo work.** All target-repo commands run via `bin/devcontainer-run '<cmd>'`. Never call project tools (linters, test runners, formatters, interpreters) on the host. (ADR 0004)
- **Never fabricate.** If a verification step fails or an ADR doesn't cover a case, say so. Don't invent citations or outcomes.
- **No secrets.** No API keys, tokens, or credentials in any file — not in comments, not in examples.
- **Mentat names no target-repo toolchain.** The driver and all Mentat files are agnostic — they do not reference specific languages, test frameworks, or build tools. Those live in the target repo's own docs (ADR 0004).

## Naming Conventions

| Layer | Convention | Examples |
|---|---|---|
| Skills | kebab-case, verb-noun or role-noun | `caveman`, `crew-research`, `to-implement` |
| Commands (`to-*`) | kebab-case, `to-` prefix | `to-plan`, `to-rebase`, `to-scaffold` |
| Crew agents | kebab-case, `crew-` prefix | `crew-review-plan`, `crew-review-bugs` |
| ADRs | `NNNN-kebab.md` | `0004-parallel-slicing-orchestration.md` |
| Worktree slugs | `dmux-<epoch>-<pid>-<rand>` | `dmux-1780705140700` |

Reference [STYLE.md](STYLE.md) for frontmatter shapes and body structure per file class.

## Workflow Rules

When editing prompt files in `.agents/`:

1. Read the relevant ADRs for the area you're touching (`docs/adr/`). System ADRs always; the target repo's `docs/adr/` when working there.
2. Run verification with `bin/devcontainer-run '<test cmd>'` if the target repo has one.
3. Commit via `/to-commit` (routes through devcontainer if one exists).

### Promotion workflow

Until Mentat has release tags, promote harness changes to the user's global install:

```bash
cp -R .agents/ ~/.agents/
```

This overwrites the global `~/.agents/` with the repo's version. Run only when `.agents/` changes are stable and reviewed.

Directory index: see [.agents/AGENTS.md](.agents/AGENTS.md) for the harness layout.

## See also

- [CONTEXT.md](CONTEXT.md) — glossary (slice/chunk/batch/land/eject/…) + ADR index + flagged ambiguities
- [STYLE.md](STYLE.md) — frontmatter shapes, body structure, forbidden words, voice rules per file class
- [README.md](README.md) — public overview, quickstart, no-framework thesis
- [.agents/AGENTS.md](.agents/AGENTS.md) — global-style harness rules (sub-agent delegation, container rule, ADR index)
