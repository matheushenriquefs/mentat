# Style

Writing rules for skills, commands, and crew-agent definitions in Mentat and its target repos. Each rule cites an exemplar from the three-source canon.

Exemplars drawn from in-repo files: `.agents/agents/crew-*.md` and `.agents/commands/to-*.md`.

## Forbidden words

Drop from all files: `just`, `simply`, `really`, `basically`, `actually`. Drop pleasantries: `sure`, `certainly`, `of course`, `happy to`. Drop hedging: `might want to`, `you could try`, `feel free to`.

## Frontmatter

Three shapes — one per file class. Use the exact keys below; no extras unless listed as optional.

**Pocock-style skill:**
```yaml
---
name: <skill-name>
description: <third-person, "Use when..." trigger clause>
---
```
Optional: `argument-hint` (user-facing hint for `$ARGUMENTS`). `disable-model-invocation: true` (rare — ultra-lightweight trigger only, e.g., `zoom-out`).

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
`tools` is a hard read-only guarantee — no read-write tools unless the agent must write (rare). Multi-line via `>` YAML anchor.

Exemplar: `.agents/agents/mentat-researcher.md` — `description: > Read-only fact locator…`

**to-* command:**
```yaml
---
description: <imperative, action-verb-first, one sentence>
---
```
No other keys.

## Body structure by file class

**Pocock-style skill:** Three-level hierarchy.
```
# Title                       ← matches frontmatter name
## Phase N — Name             ← or ## Section Name
### Substep or type           ← optional third level
```
Phase naming: `Phase N — <Name>` (from `diagnose`, `tdd`, `triage`). Step naming: numbered list inside sections. Checklists: `- [ ] item`.

**Crew-agent definition:** Flat, one level only.
```
## Section
```
No `###`. No sub-sections. Caveman-ultra fragments. No code blocks unless the output schema requires exact formatting.

Exemplar: `.agents/agents/mentat-bug-reviewer.md` — flat `## Output`, `## Blacklist`, `## Refusals`.

**to-* command:** Numbered list, no headers.
```
1. `/caveman ultra`.
2. Step two.
3. Conditional: `gate_pass → continue. Any veto → fix, re-commit.`
```
No `##` headers. No `###`. ≤ 30 lines total.

## Code blocks

| File class | Frequency | Bash lang-tag |
|---|---|---|
| Pocock skill | Moderate | Required for shell |
| Crew agent | Rare — structured prose templates only | Required if used |
| to-* command | High — bash-heavy | Required for shell |

Inline backticks for paths, variables, symbols, and command names.

## Tables

Rare. Prefer definition-list blocks (Pocock CONTEXT.md shape) for terms. Use pipe-table only for parameter matrices or comparison grids.

## Length

| File class | Target | Max before offload |
|---|---|---|
| Pocock skill | 75–110 lines | 120 lines → offload to `references/` |
| Crew agent | 60–85 lines | — |
| to-* command | ≤ 30 lines | — |

Past-median: break into a sibling reference file and link with `[text](path)`.

## Voice

| File class | Voice | Articles |
|---|---|---|
| Pocock skill | Imperative, terse | Kept |
| Crew agent | Caveman fragments | Dropped |
| to-* command | Imperative, terse | Kept |

## Cross-references

Inline markdown links: `[text](path)`. Relative paths preferred. No wiki-links (`[[…]]`). No bare paths.

In to-* commands, reference skills by invocation: `/skill-name`. No inline links.

## Shell conventions

Bash + `jq` only on the host (ADR 0004). Target-repo tools run via `mentat-container-run '<cmd>'` — never called directly on the host. No host `python3`/`node`/`uv` references in Mentat files. Language tag `bash` required on shell blocks.
