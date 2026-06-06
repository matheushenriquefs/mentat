# Mentat — Agent Guidelines

Rules for agents working inside Mentat — the orchestration harness.

See [CONTEXT.md](CONTEXT.md) for the full glossary and ADR index. See [README.md](README.md) for the public overview.

## Critical Constraints

- **Devcontainer-only execution for target-repo work.** All target-repo commands run via `bin/mentat-container-run '<cmd>'`. Never call project tools (linters, test runners, formatters, interpreters) on the host. (ADR 0004)
- **Never fabricate.** If a verification step fails or an ADR doesn't cover a case, say so. Don't invent citations or outcomes.
- **No secrets.** No API keys, tokens, or credentials in any file — not in comments, not in examples.
- **Mentat names no target-repo toolchain.** The driver and all Mentat files are agnostic — they do not reference specific languages, test frameworks, or build tools. Those live in the target repo's own docs (ADR 0004).

## Naming Conventions

| Layer | Convention | Examples |
|---|---|---|
| Skills / agents | kebab-case, `mentat-` prefix or role-noun | `caveman`, `mentat-bug-reviewer`, `mentat-implement` |
| Commands | kebab-case, `mentat-` prefix | `mentat-plan`, `mentat-rebase`, `mentat-scaffold` |
| ADRs | `NNNN-kebab.md` | `0004-parallel-slicing-orchestration.md` |
| Worktree slugs | `mentat-<epoch>-<pid>-<rand>` | `mentat-1780705140700` |

Frontmatter shapes and body structure per file class are defined in the [Style](#style) section below.

## Workflow Rules

When editing prompt files in `.agents/`:

1. Read the relevant ADRs for the area you're touching (`docs/adr/`). System ADRs always; the target repo's `docs/adr/` when working there.
2. Run verification with `bin/mentat-container-run '<test cmd>'` if the target repo has one.
3. Commit via `/mentat-commit` (routes through devcontainer if one exists).

### Promotion workflow

Until Mentat has release tags, promote harness changes to the user's global install:

```bash
cp -R .agents/ ~/.agents/
```

This overwrites the global `~/.agents/` with the repo's version. Run only when `.agents/` changes are stable and reviewed.

Directory index: see [.agents/AGENTS.md](.agents/AGENTS.md) for the harness layout.

## Comment Hygiene

Default: write no comments. Add one only when the *why* is non-obvious — a hidden constraint, subtle invariant, or workaround for a specific bug.

- Comment *why*, not *what*. Well-named identifiers explain what.
- No commented-out code. Delete it.
- No TODO comments. File an ADR or an issue.
- One short line max. No narrative essays inside functions.
- Docstring/header for public entry points only.
- No references to current task, fix, or callers ("used by X", "added for Y") — those belong in the PR description and rot as the codebase evolves.
- Remove duplicate comment blocks. One canonical statement per fact.

## Style

Writing rules for skills, commands, and crew-agent definitions in Mentat and its target repos.

### Forbidden words

Drop from all files: `just`, `simply`, `really`, `basically`, `actually`. Drop pleasantries: `sure`, `certainly`, `of course`, `happy to`. Drop hedging: `might want to`, `you could try`, `feel free to`.

### Frontmatter

Three shapes — one per file class. Use the exact keys below; no extras unless listed as optional.

**Pocock-style skill:**
```yaml
---
name: <skill-name>
description: <third-person, "Use when..." trigger clause>
---
```
Optional: `argument-hint` (user-facing hint for `$ARGUMENTS`). `disable-model-invocation: true` (rare — ultra-lightweight trigger only).

**Crew-agent definition:**
```yaml
---
name: <crew-name>
description: >
  <one-sentence summary.>
  <two-sentence detail. Output contract. Refusal statement.>
tools: [Tool1, Tool2]
---
```
`tools` is a hard read-only guarantee — no read-write tools unless the agent must write (rare).

Exemplar: `.agents/agents/mentat-researcher.md` — `description: > Read-only fact locator…`

**mentat-* command:**
```yaml
---
description: <imperative, action-verb-first, one sentence>
---
```
No other keys.

### Body structure by file class

**Pocock-style skill:** Three-level hierarchy.
```
# Title                       ← matches frontmatter name
## Phase N — Name             ← or ## Section Name
### Substep or type           ← optional third level
```
Phase naming: `Phase N — <Name>`. Step naming: numbered list inside sections. Checklists: `- [ ] item`.

**Crew-agent definition:** Flat, one level only.
```
## Section
```
No `###`. No sub-sections. Caveman-ultra fragments. No code blocks unless the output schema requires exact formatting.

Exemplar: `.agents/agents/mentat-bug-reviewer.md` — flat `## Output`, `## Blacklist`, `## Refusals`.

**mentat-* command:** Numbered list, no headers.
```
1. `/caveman ultra`.
2. Step two.
3. Conditional: `gate_pass → continue. Any veto → fix, re-commit.`
```
No `##` headers. No `###`. ≤ 30 lines total.

### Code blocks

| File class | Frequency | Bash lang-tag |
|---|---|---|
| Pocock skill | Moderate | Required for shell |
| Crew agent | Rare — structured prose templates only | Required if used |
| mentat-* command | High — bash-heavy | Required for shell |

Inline backticks for paths, variables, symbols, and command names.

### Length

| File class | Target | Max before offload |
|---|---|---|
| Pocock skill | 75–110 lines | 120 lines → offload to `references/` |
| Crew agent | 60–85 lines | — |
| mentat-* command | ≤ 30 lines | — |

### Voice

| File class | Voice | Articles |
|---|---|---|
| Pocock skill | Imperative, terse | Kept |
| Crew agent | Caveman fragments | Dropped |
| mentat-* command | Imperative, terse | Kept |

### Cross-references

Inline markdown links: `[text](path)`. Relative paths preferred. No wiki-links (`[[…]]`). No bare paths.

In mentat-* commands, reference skills by invocation: `/skill-name`. No inline links.

### Shell conventions

Bash + `jq` only on the host (ADR 0004). Target-repo tools run via `mentat-container-run '<cmd>'` — never called directly on the host. No host interpreter references in Mentat files. Language tag `bash` required on shell blocks.

## Quality Gates

Every modified file must pass its class checker before commit.
Run locally: `lefthook run pre-commit --files $(git diff --name-only "$base")`.
Wired into `mentat-orchestrate` pre-land step via lefthook (host-side; harness tools only — ADR 0004).
Checker dispatch: [.agents/bin/mentat-gate-checks](.agents/bin/mentat-gate-checks) (invoked by lefthook).

| Class | Glob | Check |
|-------|------|-------|
| ADR | docs/adr/*.md | All three sections present: ## Context, ## Decision, ## Consequences |
| Skill/agent | agents/*.md | YAML frontmatter present (first 10 lines contain ---) |
| Command | commands/*.md | YAML frontmatter present (first 10 lines contain ---) |
| Workflow doc | AGENTS.md,CONTEXT.md,README.md | Cross-ref links present ([text](*.md) syntax) |
| Shell | bin/**/*,lib/**/*.sh | bash -n + shellcheck (advisory if absent) |
| Config | *.jsonc | sed \| jq -e validates JSON structure |
| Harness | bin/lib/harness/*.sh | harness_<name>_cmd and harness_<name>_output_format both defined |

Unknown file classes pass silently (gate is additive, not a whitelist).

See [.agents/bin/lib/gates.sh](.agents/bin/lib/gates.sh) for checker implementations and [.agents/bin/mentat-gate](.agents/bin/mentat-gate) for the driver.

**Doc-freshness gate (advisory):** Any change in `.agents/bin/`, `.agents/skills/`, `.agents/commands/`, or `docs/adr/` that alters public surface must include a corresponding update to `README.md` or `CONTEXT.md`. The gate lists affected docs; the LLM reviewer flags actual staleness.

**Sync-upstream gate:** If `upstreams.jsonc` is modified, a fresh `bin/mentat-sync-upstream` run is required before commit. If >24 h since last sync (per `bin/mentat-sync-check`), a warning is emitted.

## Test-when-modified

Modifying certain file classes requires additional checks before commit:

| Trigger | Required action |
|---|---|
| `agents/*.md` or `skills/*/SKILL.md` modified | Run `.agents/bin/mentat-gate <file>` + skill's promptfoo eval (`npx promptfoo eval --filter-providers <skill-name>`) |
| `docs/adr/*.md` modified | File must include `**Decided:** <YYYY-MM-DD>` and `**Author:** <handle>` lines |
| `agents/mentat-*-reviewer.md` modified | Must bump ADR-0003 weight rationale (add/update reasoning for any changed dimension weight) |

Enforced by convention during review. `.agents/bin/mentat-gate` flags structural violations; the LLM reviewer flags missing promptfoo eval evidence in the PR diff.

## See also

- [CONTEXT.md](CONTEXT.md) — glossary (slice/chunk/batch/land/eject/…) + ADR index + flagged ambiguities
- [README.md](README.md) — public overview, quickstart, no-framework thesis
- [CREDITS.md](CREDITS.md) — vendored skill attributions (auto-generated)
- [.agents/AGENTS.md](.agents/AGENTS.md) — system harness rules (sub-agent delegation, container rule, ADR index)
