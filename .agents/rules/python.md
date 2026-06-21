---
paths:
  - ".agents/skills/*/scripts/*.py"
  - ".agents/lib/**/*.py"
  - "tests/**/*.py"
---

# Python

Mentat is stdlib-only at runtime (ADR-0008): argparse CLIs, no third-party runtime
dependency. The dev layer is `ruff` (format and lint), `pyright` (types), and
`pytest`. These rules govern the `.py` files under the paths above.

## Language

- Type-hint every parameter and return value.
- Use PEP 585 generics and union syntax (`list[X]`, `dict[K, V]`, `set[X]`,
  `tuple[X, ...]`, `X | None`, `X | Y`), never the legacy `typing` aliases
  (`List`, `Dict`, `Optional`, `Union`). New code, and any signature you edit, use
  the new form even in a file that mixes styles.
- Use f-strings for formatting.
- A boolean parameter is keyword-only: `def f(path, *, dry_run: bool = False)`, so a
  caller cannot pass it positionally. This pairs with the no-flag-argument rule
  below — a kept boolean is a mode the function reads, never a switch between two
  behaviors.
- Use `from __future__ import annotations` at the top of every module. Use a
  `TYPE_CHECKING` guard only to break a real import cycle, not as a default; prefer
  to fix a cycle structurally (see `architecture.md`).
- Do not add `# type: ignore` without a reason in a trailing comment. A bare ignore
  hides a real type error.

## Control flow

- Use guard clauses and early return. Handle the error, empty, or edge case first
  and return, so the main path is not nested inside a conditional.
- Do not write `else` after a branch that returns. The code after the `if` is
  already the `else`.
- Avoid `if`/`elif`/`else` chains where guard clauses fit. A chain that maps an
  input to one value is a dict lookup or a small mapping, not a ladder.
- Cap nesting at two levels. Deeper than that, extract a function.
- Extract a complex conditional into a named boolean and combine several conditions
  with `all(...)` or `any(...)`, so the test reads as one intention:
  `is_ready = all([is_loaded, has_quota, not is_stale])`. Do not inline a
  multi-clause condition directly in the `if`.

## Functions and naming

- Write small, pure functions that work at one level of abstraction. A function
  decides or does, not both.
- Keep command and query separate. A function that returns a value does not also
  mutate state; a function that mutates returns `None`.
- Do not pass a flag argument that switches behavior. Split it into two functions
  with intention-revealing names (`load_sibling` and `load_skill`, not
  `load(kind)`).
- Use intention-revealing names. No cryptic abbreviations: `worktree`, not `wt` in
  a public signature; `plan_path`, not `pp`.
- Name every constant. No magic number or string in logic — thresholds, exit codes,
  and limits get a module-level named constant (`PLAN_THRESHOLD = 0.88`).
- Apply DRY, but do not abstract before a second real use. Two similar lines are
  cheaper than the wrong abstraction. A wrapper that exists only for ergonomics is
  not a second use — remove the need for the wrapper instead.

## Immutability

- Never mutate a function argument in place. Return a new value. A caller that
  passes a list does not expect it reordered or appended to.
- Prefer immutable data: `@dataclass(frozen=True)` for a value carried across a
  boundary, `tuple`/`frozenset` over the mutable forms where the value does not
  change after construction.
- Handle `None` and empty explicitly. Write total functions that have a defined
  answer for every input, rather than letting an empty list or missing key raise
  deep in the call stack.

## Output

- Program output goes to stdout; diagnostics, progress, and warnings go to stderr.
  A CLI's real result and its diagnostics stay separable, so a caller can pipe one
  without the other.
