# Style Guide — Mentat Skills and Agents

Writing rules for all files in `.agents/skills/`, `.agents/agents/`, and `docs/`.
Structural framing follows [Diátaxis](https://diataxis.fr/) — reference for spec files,
how-to for workflow docs.

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

### Full Skill

Used for: `mentat-prd`, `mentat-tasks`, `mentat-implement`, `mentat-orchestrate`,
`mentat-container`, `mentat-log`, `mentat-session`, `mentat-git`, `mentat-plan`, `mentat-skill`.

- Frontmatter: `name` + `description` only.
- Description: third-person, "Use when..." trigger clause.
- Body: `## Phase N — Name` or `## Section Name` → `### Substep` (optional third level).
- Prefer `## Rules` or `## Constraints` over `## Invariants`.
- Do not use `## Toolchain discovery` or `## Atomic contract`.
- Articles: kept.
- LOC budget: 75–120.

### Agent

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
| `.agents/skills/mentat-install/SKILL.md` | Thin Skill | ≤40 |
| `.agents/skills/mentat-{prd,tasks,implement,orchestrate,container,log,session,git,plan,skill}/SKILL.md` | Full Skill | 75–120 |
| `.agents/agents/mentat-*-reviewer.md` | Agent | 60–100 |
| `.agents/agents/mentat-researcher.md` | Agent | 60–100 |
| `docs/*.md` | Diátaxis (free) | n/a |
| `AGENTS.md` | — | ≤150 |
| `CONTEXT.md` | Glossary | n/a |

---

## Frontmatter

Three shapes; use exact keys only.

**Thin Skill / Full Skill:**
```yaml
---
name: <skill-name>
description: <third-person, "Use when..." trigger clause>
---
```
Optional: `argument-hint` (user-facing hint for `$ARGUMENTS`).
Do not add `metadata:`, `version:`, or any other keys.

**Agent:**
```yaml
---
name: <agent-name>
description: >
  <one-sentence summary.>
  <output contract. Refusal statement.>
tools: [Tool1, Tool2]
---
```

---

## Body Structure

**Thin Skill:** Numbered action list. No `##` headers.

**Full Skill:** `# Title` → `## Phase N — Name` → `### Substep` (optional).

**Agent:** `## Section` only. No `###`. No nested sub-sections.

---

## Forbidden Words

Drop from all files: `just`, `simply`, `really`, `basically`, `actually`, `obviously`.
Drop pleasantries: `sure`, `certainly`, `of course`, `happy to`.
Drop hedging: `might want to`, `feel free to`.

Agents additionally drop all articles (`a`, `an`, `the`) from body prose.

---

## Code Blocks

| Class | Frequency | Language tag |
|---|---|---|
| Thin Skill / Full Skill | Moderate | Required for shell (`bash`) |
| Agent | Rare | Required if used |

Inline backticks for: paths, variables, symbols, command names.

---

## Cross-References

- Skills: use `/skill-name` invocation notation.
- Prose: use `[text](path)` markdown links, relative paths preferred.
- No wiki-links (`[[…]]`). No bare paths without backtick.
- Agents: self-contained. No cross-references.

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
How-to docs (skill SKILL.md files): task-oriented, step-by-step.

---

## Enforcement

- **Tier 1 — deterministic** (`.agents/lib/style/lint.py`): frontmatter keys, LOC budget,
  banned words, article-drop for agents. Runs in lefthook `pre-commit` as `style-lint`.
  Commit blocked on violation.
- **Tier 2 — semantic** (promptfoo, `task eval`): voice class conformance, structural rules,
  third-person and "Use when..." trigger presence. Runs on PR.
