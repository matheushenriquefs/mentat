# ADR 0008 — Code Smell Review

**Decided:** 2026-06-06
**Author:** matheussantosh

## Context

ADR 0003 gates runtime correctness via bug-reviewer (veto), plan alignment via plan-reviewer (threshold), and test faithfulness via test-reviewer (threshold). No reviewer targets maintainability rot: Long Method, Feature Envy, Shotgun Surgery, Primitive Obsession, and the other 18 smells cataloged at refactoring.guru.

Adding a smell reviewer raises the question of whether it should gate (block a land) or advise. Gating on smells creates friction: smell severity is inherently subjective, smells accumulate over time and can't always be resolved in the same chunk that introduced them, and no Mastra scorer maps to source-code smells (unlike plan alignment → PromptAlignment, or bug severity → latent-bug lens).

## Decision

Add `mentat-smell-reviewer` as a **new advisory axis** — never veto, never threshold.

Split into two layers:
- `bin/lib/smells.sh` — deterministic detectors (Long Method, Long Parameter List, Magic Numbers, Nested Conditional, Duplicate Block). Fast, cheap, zero LLM cost.
- `agents/mentat-smell-reviewer.md` — LLM pass covering all 22 refactoring.guru smells, focused on the smells that require semantic understanding (Feature Envy, Shotgun Surgery, Divergent Change, Refused Bequest, Inappropriate Intimacy, Data Class, Speculative Generality, Dead Code).

Findings surface as `smell_findings[]` lines analogous to bug-reviewer's `design_drift[]`. Output format: `path:line: <smell>. <fix>.`

Bug-reviewer / smell-reviewer line:
- Runtime bugs (race, leak, injection, null-deref) → `mentat-bug-reviewer`, veto authority.
- Maintainability rot (method length, coupling, cohesion) → `mentat-smell-reviewer`, advisory.

This follows ADR-0003's "reimpl math in prompts, no code dep" pattern — the LLM is the scorer, not a Mastra metric.

## Consequences

- Smell findings appear in review output but never block a land.
- `smells_check <file>` callable standalone from any script or pre-commit hook.
- Adding a new smell detector = adding one `smell_<name>()` function to `smells.sh` + one call in `smells_check`.
- No Mastra mapping required. No ADR-0003 gate weight change.
