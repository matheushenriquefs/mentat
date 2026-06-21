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
