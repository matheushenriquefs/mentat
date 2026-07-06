---
name: mentat-plan
description: Write and resolve mentat plan files. Use when you need to create a new plan file or canonicalize a plan slug-or-path reference.
---

Write structured plan files to `~/.agents/plans/` and resolve plan slug-or-path references to canonical absolute paths. Plans capture grilled requirements as tracer-bullet vertical slices, each AFK- or HITL-tagged, with explicit `blocked_by` between dependent slices.

## How to invoke

In-harness slash command (lead form):

```
/mentat-plan <subcommand> <args>
```

Underlying call (what the slash form runs):

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

## Authoring flow

1. Slugify the subject for the plan path: `~/.agents/plans/<slug>.md`.
2. Grill requirements against `CONTEXT.md` and ADRs (created lazily as decisions crystallize).
3. Decompose into tracer-bullet vertical slices.
4. Tag each slice **AFK** (gate clears unattended → eligible to auto-spawn) or **HITL** (needs an architectural call → anchors in calling session).
5. Note `blocked_by` between slices for true dependencies; orchestrator topo-sorts.
6. Write body to a temp file, then `plan.py write <slug> <temp-path>`.
7. `write` suggests `/mentat-tasks <slug>`. Handoff: **plan → tasks → track** — materialize slices with `/mentat-tasks`, then `mentat-session track`.

## Tracer-bullet slicing

Each slice cuts through every layer end-to-end and is verifiable alone. Prefer thin over thick — the slice is the orchestration unit, so a clean vertical cut is why parallel chunks compose instead of colliding — but not below the transaction-cost floor (see **Slice sizing**).

A slice is well-formed when:
- It can be implemented, tested, and reviewed without partial work from any sibling.
- Its diff lives in a bounded set of paths.
- Its gate passes deterministically on its own merits (red test → green).

## Slice sizing

A slice runs as one chunk under a wall-clock timeout (`chunk_timeout`, default 1800s). That
same wall also pays for container startup, one red→green cycle, and the full land gate. Size a
slice to finish inside the wall with room to spare — aim for about half of it. A slice that needs
the whole wall times out and ejects.

Do not size by guessing how long the work will take; such estimates are unreliable. Size by the
shape of the work instead:

- one behavior, one red→green cycle,
- a bounded, non-overlapping set of files,
- no dependence on a sibling's unfinished work.

There is a floor. Every slice pays for startup and a full gate, so merge a cluster of trivial
slices, and split one that projects near the wall. When you have past `chunk_started`→`chunk_landed`
times for similar slices, size against those — measured times beat any estimate.

## Sibling-plan split

If slices form ≥2 groups with disjoint write-sets and no chain between groups, emit one sibling plan per group plus a parent index file:

```
mentat-thing.md           # parent index: lists sibling plans, no slices
mentat-thing-core.md      # sibling A: core slices
mentat-thing-ui.md        # sibling B: ui slices
```

Otherwise emit one plan. The heuristic exists so `mentat-orchestrate` can fan groups in parallel without artificial barriers.

### Parent-index frontmatter contract

The parent index MUST declare its siblings with `siblings:` and MUST have empty `blocked_by`:

```
---
id: mentat-thing
status: ready
class: AFK
blocked_by: []          # MUST be empty — parent indexes do not participate in topo sort
siblings: [mentat-thing-core, mentat-thing-ui]  # MUST list all sibling slugs (no .md suffix)
created_at: 2026-06-13
---
```

`mentat-orchestrate` expands parent `siblings:` before routing — same schedule as passing every sibling ref. Dependent plans list sibling slugs in `blocked_by`, not the parent.

## Rules

- Plan frontmatter requires `id`, `status`, `class`, `blocked_by`. Optional: `parent`, `supersedes`, `created_at`.
- `class` is `AFK` or `HITL`; lives in frontmatter, never overridden at runtime.
- `blocked_by` lists slugs (not paths). Frontmatter parsing and cycle detection live in `mentat-orchestrate` (exits 65 on either).
- Slug doubles as the plan's `id` field; filename and `id` should match or orchestrator topo-sort gets confused.
- One commit per slice (`mentat-implement` contract); no squash. Stdlib-only scripts — frontmatter parsing delegated to `mentat-orchestrate` (no PyYAML).

## Constraints

- Plan files live under `~/.agents/plans/` only; no project-local plan storage.
- `write` overwrites an existing plan at the same slug without warning — slug collisions are caller responsibility.
- `resolve-slug` is pure path arithmetic; it does not stat or validate the slug.
- All audit emissions route through `mentat-log emit`; the skill never writes JSONL directly.
- `write` is atomic only at the OS level: a successful write emits `plan.succeeded`; an `OSError` emits `plan.failed` and propagates to the caller.
