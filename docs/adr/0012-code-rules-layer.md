# ADR 0012: Code-rules layer

Status: Accepted
Date: 2026-06-20

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

**Staged enforcement.** Both `mentat-rules-reviewer` (new) and
`mentat-context-reviewer` (already present, until now invoked by hand) enter the
scored gate (ADR-0003) as **advisory** — verdict `advise`, never a veto. A later
change promotes them to enforcing once the tree conforms to the rules. Gating them
as a veto before the existing tree conforms would block every commit, so advisory
is the only safe entry state. The promotion records the threshold chosen.

## Consequences

- A code rule now has a single home and a reviewer that reads it. Adding a rule is
  a new `paths:`-scoped section, not a line buried in `AGENTS.md`.
- Two reviewers split the work without overlap: `mentat-rules-reviewer` owns
  code-rule conformance and lexicon contradictions; `mentat-context-reviewer` owns
  prose and prompt residue. Their verdict bases do not intersect.
- The advisory entry means the gate's behavior does not change on the day the
  layer lands — findings surface, nothing blocks — until the promotion flips them.
