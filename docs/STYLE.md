# Style Guide — Mentat Skills, Agents, and Commands

Writing rules for all files in `.agents/skills/`, `.agents/agents/`, and `docs/`.
Structural framing follows [Diátaxis](https://diataxis.fr/) — reference for spec files,
how-to for workflow docs. Voice rules are mentat-specific, derived from 34 files across
Pocock skills, crew agents, and mentat commands (see `context/style-invariants.md`).

Enforced by: Tier 1 deterministic linter (`.agents/lib/style/lint.py`, lefthook pre-commit).
Tier 2 semantic conformance: promptfoo eval (`task eval`).

---

## Voice Classes

Three classes; every file maps to exactly one.

### Thin Skill

Used for: `mentat-install`.

- Frontmatter: `name` + `description` only. No `metadata:`, no `version:`.
- Description: third-person, "Use when..." trigger clause.
- Body: numbered action list ≤6 steps. No `## Phase`. Delegates to Python script.
- Articles: kept.
- LOC budget: ≤40.

### Full Pocock Skill

Used for: `mentat-prd`, `mentat-tasks`, `mentat-implement`, `mentat-orchestrate`,
`mentat-container`, `mentat-log`, `mentat-session`, `mentat-git`, `mentat-plan`, `mentat-skill`.

- Frontmatter: `name` + `description` only.
- Description: third-person, "Use when..." trigger clause.
- Body: `## Phase N — Name` or `## Section Name` → `### Substep` (optional third level).
- Prefer `## Rules` or `## Constraints` over `## Invariants`.
- Do not use `## Toolchain discovery` or `## Atomic contract`.
- Articles: kept.
- LOC budget: 75–120.

### Crew Agent

Used for: `mentat-researcher`, reviewers, all files in `.agents/agents/`.

- Frontmatter: `name` + `description` (multi-line `>`) + `tools` list.
- Description: one-sentence summary + output contract + refusal statement, via `>`.
- Body: flat `##` sections only. No `###`. Caveman-compressed fragments.
- Articles: dropped (`a`, `an`, `the` absent from body prose).
- Arrow notation: `→` for causality or state transitions.
- LOC budget: 60–100.
- Exemplar: `.agents/agents/mentat-researcher.md`.

---

## Voice-Mapping Table

| Path pattern | Voice class | LOC budget |
|---|---|---|
| `.agents/skills/mentat-install/SKILL.md` | Thin skill | ≤40 |
| `.agents/skills/mentat-{prd,tasks,implement,orchestrate,container,log,session,git,plan,skill}/SKILL.md` | Full Pocock | 75–120 |
| `.agents/agents/mentat-*-reviewer.md` | Crew | 60–100 |
| `.agents/agents/mentat-researcher.md` | Crew | 60–100 |
| `docs/*.md` | Diátaxis (free) | n/a |
| `AGENTS.md` | — | ≤150 |
| `CONTEXT.md` | Glossary | n/a |

---

## Frontmatter

Three shapes; use exact keys only.

**Thin skill / Full Pocock skill:**
```yaml
---
name: <skill-name>
description: <third-person, "Use when..." trigger clause>
---
```
Optional: `argument-hint` (user-facing hint for `$ARGUMENTS`).
Do not add `metadata:`, `version:`, or any other keys.

**Crew agent:**
```yaml
---
name: <agent-name>
description: >
  <one-sentence summary.>
  <output contract. Refusal statement.>
tools: [Tool1, Tool2]
---
```

**Slash-command file:**
```yaml
---
description: <imperative, action-verb-first, one sentence>
---
```
No other keys.

---

## Body Structure

**Thin skill:** Numbered action list. No `##` headers.

**Full Pocock skill:** `# Title` → `## Phase N — Name` → `### Substep` (optional).

**Crew agent:** `## Section` only. No `###`. No nested sub-sections.

**Slash-command file:** Numbered list, no headers, ≤30 lines.

---

## Forbidden Words

Drop from all files: `just`, `simply`, `really`, `basically`, `actually`, `obviously`.
Drop pleasantries: `sure`, `certainly`, `of course`, `happy to`.
Drop hedging: `might want to`, `feel free to`.

Crew agents additionally drop all articles (`a`, `an`, `the`) from body prose.

---

## Code Blocks

| Class | Frequency | Language tag |
|---|---|---|
| Thin / Full skill | Moderate | Required for shell (`bash`) |
| Crew agent | Rare | Required if used |
| Slash-command | High | Required for shell |

Inline backticks for: paths, variables, symbols, command names.

---

## Cross-References

- Skills/commands: use `/skill-name` invocation notation.
- Prose: use `[text](path)` markdown links, relative paths preferred.
- No wiki-links (`[[…]]`). No bare paths without backtick.
- Crew agents: self-contained. No cross-references.

---

## Special Markers

- **Arrow notation** `→`: causality, state transitions, conditional branches.
- **Bold**: keywords, principles, warnings. No italics alone.
- **Checklists**: `- [ ] item` for verification steps (skills only).
- **Callouts**: blockquotes (`>`) for format/template examples only.

---

## Structural Framing (Diátaxis)

`docs/` files follow [Diátaxis](https://diataxis.fr/): reference vs. explanation vs. how-to
for contributor-facing docs. Skill and agent files follow their voice class above.

Reference docs (this file, EXIT-CODES.md, PLUGINS.md): information-oriented, scan-friendly.
Explanation docs (CONTEXT.md, ADRs): understanding-oriented, prose-heavy.
How-to docs (INSTALLER.md): task-oriented, step-by-step.

---

## Enforcement

- **Tier 1 — deterministic** (`.agents/lib/style/lint.py`): frontmatter keys, LOC budget,
  banned words, article-drop for crew agents. Runs in lefthook `pre-commit` as `style-lint`.
  Commit blocked on violation.
- **Tier 2 — semantic** (promptfoo, `task eval`): voice class conformance, structural rules,
  third-person and "Use when..." trigger presence. Runs on PR.
