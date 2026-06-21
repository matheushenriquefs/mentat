# ADR 0012: Code-rules layer

Status: Accepted (locked)
Date: 2026-06-20
Amended: 2026-06-21 (v2 — both reviewers promoted to veto; advisory phase complete)

## Context

Mentat governs prose with `docs/STYLE.md` (three voice classes) and enforces it
with a deterministic linter (`.agents/lib/style/lint.py`) plus a promptfoo eval.
That layer rules words — frontmatter keys, LOC budgets, banned words, article-drop.
It says nothing about *code*: control flow, function shape, immutability, how a
module is organized. Those conventions live in scattered prose (`AGENTS.md`
comments rule, ADR-0008 runtime notes) and are enforced only by whatever a
reviewer happens to notice. A guard-clause rule or a no-in-place-mutation rule has
no home and no gate.

## Decision

Add `.agents/rules/` — a layer of path-scoped, enforceable **code** rules,
distinct from `docs/STYLE.md`. Two layers, two authorities:

- `docs/STYLE.md` — prose authority. Voice classes for skill and agent files,
  forbidden words, LOC budgets, canonical-prose. Enforced by `lint.py` (Tier 1)
  and promptfoo (Tier 2).
- `.agents/rules/` — code authority. Each file carries `paths:` frontmatter (the
  globs it governs) and prose rules for code under those globs. Enforced by
  `mentat-rules-reviewer` (semantic) and the runtime's `ruff`/`pyright` (ADR-0008).

The initial rule files are `python.md` (control flow, functions and naming,
immutability) and `architecture.md` (group by function, module interface and
imports). They state mentat's stdlib-only argparse conventions; database- or
framework-specific clauses do not apply and are absent.

**Staged enforcement (complete).** Both `mentat-rules-reviewer` (new) and
`mentat-context-reviewer` entered the scored gate (ADR-0003) as **advisory** until
the tree conformed. As of 2026-06-21 both are **veto** gates — zero violations and
zero residue findings required. A full-tree scan confirmed clean before promotion.
Threshold chosen: zero tolerance (veto), matching bebop's code-rules convention.

## Consequences

- A code rule now has a single home and a reviewer that reads it. Adding a rule is
  a new `paths:`-scoped section, not a line buried in `AGENTS.md`.
- Two reviewers split the work without overlap: `mentat-rules-reviewer` owns
  code-rule conformance and lexicon contradictions; `mentat-context-reviewer` owns
  prose and prompt residue. Their verdict bases do not intersect.
- Promotion to veto required a full-tree cleanup: 34 context findings (F0/F5 code
  comments, stale `.config.jsonc` references, unresolved skill pointers) and 9 rules
  violations (2 missing return types, 7 `utils.py` filenames renamed to descriptive
  names) were resolved before the flip.
