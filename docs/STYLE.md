# Style Guide — Mentat Skills and Agents

Writing rules for all files in `.agents/skills/`, `.agents/agents/`, and `docs/`.
Structural framing follows [Diátaxis](https://diataxis.fr/) — reference for spec files,
how-to for workflow docs.

This file is the **prose** authority — voice, words, structure. Code conventions
(control flow, function shape, immutability, module layout) live in the **code**
authority, `.agents/rules/` ([ADR-0012](adr/0012-code-rules-layer.md)), enforced by
`mentat-rules-reviewer`.

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

## Canonical Prose

Committed prose describes the system as it is now, for a reader arriving today with
no memory of how it was built. Write the steady state, not the journey to it. This
governs every committed file — docs, ADR bodies, skill and agent prompts, and code
comments — not only agent prompts.

- **No version or phase leak.** Do not narrate development history — no `v0`,
  `Phase 2`, `the MVP`, `for now`, slice tags (`(S7)`, `step 3`), roadmap promises
  (`will eventually`, `to be added later`), or change narration (`previously`,
  `used to`, `we renamed`, `the old`). State the current shape; git holds the
  history. When a limit is real, state it as a present-tense fact and say why, not
  as a promise of future work.
- **No external-project references.** Name only mentat's own concepts. Do not point
  at sibling repositories or another project's conventions in committed prose. A
  borrowed idea is described on its own terms here; the borrow is recorded once in
  `CREDITS.md`.

ADR bodies are the one exception to version leak: an ADR records a decision and may
narrate the trade-off that produced it. Enforced by `mentat-context-reviewer`.

## Comments in Code

Write no comments by default. Add one only when the **why** is non-obvious — a
hidden constraint, a subtle invariant, or a workaround for a specific bug. Never
describe what the code does; well-named identifiers do that. If removing the
comment would not confuse a future reader, do not write it. No commented-out code,
no `TODO` comments.

## Documentation LOC Budgets

Hard caps on contributor-facing docs, enforced by review:

| File | Limit |
|------|-------|
| `AGENTS.md` | 150 |
| `CONTEXT.md` | 200 |
| `docs/STYLE.md` | 200 |
| `README.md` | 200 |

Skill and agent file budgets live in the voice-mapping table above.

## Enforcement

- **Tier 1 — deterministic** (`.agents/lib/style/lint.py`): frontmatter keys, LOC budget,
  banned words, article-drop for agents. Runs in lefthook `pre-commit` as `style-lint`.
  Commit blocked on violation.
- **Tier 2 — semantic** (promptfoo, `task eval`): voice class conformance, structural rules,
  third-person and "Use when..." trigger presence. Runs on PR.
