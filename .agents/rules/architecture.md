---
paths:
  - ".agents/skills/*/scripts/*.py"
  - ".agents/lib/**/*.py"
  - "tests/**/*.py"
---

# Architecture

Code is organized by function, not by structure. The files in a module belong
together because they serve the same work, not for the sake of sitting in one
folder. You should not have to hunt across modules to follow one feature.

## Group by function

Do not group by artifact type. There is no `models.py`, `types.py`, `helpers.py`,
or `utils.py` that gathers one kind of code from across the system. A generic
artifact-type filename is a sign code was grouped by structure — name a file for
the work it does.

When a module grows too large, split it by sub-concept, not by artifact type. The
gate engine is a package whose files each name their work: `engine.py` discovers
and runs gates, `score.py` aggregates reviewer verdicts, `code/precommit.py` and
`code/smells.py` are the deterministic gates themselves. None of them is a
`models.py` or a `handlers.py`.

The two surfaces follow the same rule. `.agents/lib/` holds one module per concept
(`session.py`, `worktrees.py`, `events.py`, `config.py`), each owning the data and
the logic for that concept together. `.agents/skills/*/scripts/` holds the
entry-point logic for one skill, named for the skill's job.

## Module interface and imports

- A package module exports its public interface from its `__init__.py`. A caller
  imports the name it needs, not a path into the module's internals.
- Import across module boundaries only from the top level
  (`from lib.<module> import <symbol>`). Reaching into a submodule path across a
  boundary (`from lib.<module>.<file> import ...`) couples the caller to layout
  that should stay private.
- Inside one module, siblings use relative imports (`from .frontmatter import parse`).
- A leading underscore marks a name as private to its module (`_walk.py`,
  `_discover`). Do not import an underscored name across a boundary.

## Engineering discipline

These principles govern how a change gets made, not just how it reads once
made. `.agents/rules/naming.md` and `database.md` cover vocabulary; this
section covers judgment.

- **Root-cause over band-aid.** Trace a failure to its source before
  patching the symptom. A retry loop around a flaky call, a broadened
  `except`, or a default that papers over a missing value all treat a
  symptom — fix the thing that produces the bad state instead.
- **Evidence over inference.** Ground a decision in the actual behavior of
  the system — read the source, run the failing case, check the ADR —
  before locking it in. Prefer a battle-tested library over hand-rolling,
  but confirm the standard pattern first: some hand-rolled code (a
  `user_version` migration applier, see `database.md`) *is* the standard,
  and copying a library where the stdlib already does the job adds a
  dependency for nothing.
- **Subtraction over addition.** Default to removing a moving part, not
  adding one. A new flag, a new config layer, or a new abstraction is a
  cost; prefer deleting dead code, collapsing a needless indirection, or
  solving the problem with an existing primitive. Shipped-runtime LOC
  should trend down over a series of changes, not up.
- **Model the domain.** A concept gets a typed entity with its DAO/Service
  co-located (see `Entities and data access` in `naming.md`), not a raw
  `dict` passed across a module boundary. A pure computation stays a
  function — do not wrap it in a class for the sake of having one.
- **Tests mirror the module structure.** One test module per source
  submodule: `test_<module>.py` follows `<module>.py`. No god-test-file
  that asserts across unrelated concepts — the same "no god-file"
  criterion in `Group by function` above applies to tests as to source.
- **Fail-loud over silent-mask.** Surface, raise, or log a failure —
  never continue past it with a plausible-but-wrong value or a false-green
  result. A terminal write that fails raises. A target that will not
  resolve raises. A gate given a missing or unreadable input blocks rather
  than passing.
  - Validate a reference at ingest, never resolve an unknown string
    leniently at runtime: a plan's `blocked_by` slug is checked at
    topo-sort time, a reviewer name at gate-config load time — not
    guessed later, at schedule or score time. A lenient fallback
    (defaulting an unresolved branch to `"main"`, an unresolved path to
    `Path.cwd()`) is the same smell wearing a different shape — reject
    the input instead of guessing at it.
  - Enforced at review time by the bug-reviewer latent-bug lens (fail-loud over silent-mask).
- **Per-run isolation.** Every per-run resource is keyed by `chunk_slug`
  (see the isolation lexicon in `naming.md`) — never machine-wide, never
  `Path.cwd()`. Two chunks running concurrently on the same host must not
  see each other's state.
