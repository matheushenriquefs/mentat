---
name: mentat-plan
description: >
  Write and resolve mentat plan files.
  Use when you need to create a new plan file or canonicalize a plan slug-or-path reference.
---

Write structured plan files to `~/.agents/plans/` and resolve plan slug-or-path references to canonical absolute paths.

## How to invoke

```
python3 ~/.agents/skills/mentat-plan/scripts/plan.py <subcommand> <args>
```

Subcommands: `write`, `resolve-slug`.

## Subcommands

| Subcommand | Args | Description |
|---|---|---|
| `write` | `<slug> <body-path>` | Write `~/.agents/plans/<slug>.md` from body file. Emits `plan.started` + `plan.succeeded`. |
| `resolve-slug` | `<slug-or-path>` | Print canonical absolute path. Pure — no stat. |

## Plan-ref resolution

Bare slug (no `/`, no `.md` suffix) → `~/.agents/plans/<slug>.md`.
Slash or `.md` suffix → treated as a path (expanduser + resolve).

## Flow (interactive plan writing)

1. Grill with docs → split into slices.
2. Write plan body to a temp file.
3. `python3 ~/.agents/skills/mentat-plan/scripts/plan.py write <slug> <body-path>`
4. Emits `plan.started` then `plan.succeeded` (or `plan.failed` on write error).
