---
paths:
  - ".agents/skills/*/scripts/*.py"
  - ".agents/lib/**/*.py"
  - "tests/**/*.py"
---

# Code organization

ADR-0019 locks how mentat source is laid out. These rules apply to every `.py`
file under the paths above.

## Domain, not kind

- Name a module for the concept it owns (`chunk.py`, `store.py`, `worktrees.py`),
  not for an artifact type (`models.py`, `types.py`, `handlers.py`).
- Never add `utils.py` or `helpers.py`. Extract a named submodule or inline the
  two lines — a grab-bag filename is a veto finding.
- When a module exceeds ~100 LOC, split by sub-concept inside the same package.
  Do not split by artifact type.

## Protocol + registry + adapter

- A swappable boundary (gate, harness, emit backend) exposes a `Protocol`, a
  registry that discovers implementations, and thin adapters. No god-module that
  both defines the contract and implements every variant.
- Callers import the registry entrypoint, not a private submodule path across the
  boundary (see `architecture.md`).

## Env and path change-points

- Read `MENTAT_CHUNK_ID` only through `lib.chunk.get_chunk_id_from_env()`.
- Read `MENTAT_CONFIG` only through `lib.config.get_config_dir()`.
- Frozen path constants live in `lib.support.paths` — do not duplicate
  `_SKILL_ROOT`, `default_skills_root`, or home-dir anchors in skill scripts.

## Package hygiene

- No empty `__init__.py` files. No docstring-only `__init__.py` — delete the
  file and import the submodule directly.
- Do not re-export symbols from `__init__.py` when `engine.py` (or the owning
  module) already defines them.
