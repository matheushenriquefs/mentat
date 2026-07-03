---
name: mentat-plan
description: >
  Write and resolve mentat plan files.
  Use when you need to create a new plan file or canonicalize a plan slug-or-path reference.
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
7. `write` ends by suggesting `/mentat-tasks <slug>` — run it to turn the plan's
   slices into trackable tasks. The full handoff is **plan → tasks → track**:
   author the plan here, materialize its slices as tasks with `/mentat-tasks`, then
   watch progress with `mentat-session track`.

## Tracer-bullet slicing

Each slice cuts through every layer end-to-end and is verifiable alone. Prefer thin over thick — the slice is the orchestration unit, so a clean vertical cut is why parallel chunks compose instead of colliding — but not below the transaction-cost floor (see **Slice sizing**).

A slice is well-formed when:
- It can be implemented, tested, and reviewed without partial work from any sibling.
- Its diff lives in a bounded set of paths.
- Its gate passes deterministically on its own merits (red test → green).

## Slice sizing — fit the wall, don't over-shard

Each slice runs as one orchestrated chunk under a wall-clock timeout (`chunk_timeout`, default 1800s) that also pays container cold-start + one red→green cycle + the full land gate (coverage per ADR-0014). Size so a slice **finishes inside the wall with headroom** — target roughly half of it. A slice that needs the whole wall times out and ejects (observed: cold-start + one gate ≈ 25 of 30 min).

Do **not** size by predicting duration. Neither model self-estimates nor point estimates (story points / COCOMO) are reliable for agent work — COCOMO's average error is ≈100%, and LLM agents are measurably not budget-aware (they can't forecast or self-throttle to a cost cap). Industry abandoned upfront point-estimation for *size-to-fit* + *historical throughput* (INVEST "Small"; CI timing-based test sharding). Size by the **shape** of the work instead:
- one behavior / one red→green cycle,
- a bounded, non-overlapping file-set,
- no dependence on a sibling's partial work.

There is a floor. Every slice pays a fixed transaction cost — cold-start + a full land/review gate. Shattering work below that floor spends real tokens per slice to remove risk that is already near zero. Batch size is a U-curve — transaction cost falls per unit as a slice grows, timeout/rework risk rises — with a **flat bottom**: a ~10% sizing error costs ~2–3%, so aim for the band, don't over-optimize. Rule of thumb (mirrors CI shard tuning): a slice projected near the wall → split; a cluster of trivial slices each far under the floor → merge.

Prefer historical signal when you have it: past chunk durations (`chunk.spawned`→`chunk.landed` in the audit log) are the most accurate sizing input — size a new slice against observed times of *similar* past slices, not a guess.

If the per-slice tax is the real pain, the higher-leverage fix is orchestrate-side, not sizing: drive the fixed cost down (warm/pooled containers, tiered review that reserves the full gate for risky slices). That shifts the optimum *smaller* and lets you slice finer without waste — a cheaper gate buys what a sizing guess cannot.

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

`mentat-orchestrate` reads `siblings:` and expands the parent into its sibling plans
before routing. Passing the parent ref to `orchestrate run` produces the same schedule
as passing every sibling ref directly. Any plan that depends on a sibling must list the
sibling slug (not the parent slug) in its own `blocked_by`.

## Rules

- Plan frontmatter requires `id`, `status`, `class`, `blocked_by`. Optional: `parent`, `supersedes`, `created_at`.
- `class` is `AFK` or `HITL`; lives in frontmatter, never overridden at runtime.
- `blocked_by` lists slugs (not paths). Frontmatter parsing and cycle detection live in `mentat-orchestrate` (exits 65 on either).
- Slug doubles as the plan's `id` field; filename and `id` should match or orchestrator topo-sort gets confused.
- One commit per slice during implementation (`mentat-implement` contract); no squash.
- Script body is stdlib-only; no PyYAML dependency (frontmatter parsing is delegated to `mentat-orchestrate`).

## Constraints

- Plan files live under `~/.agents/plans/` only; no project-local plan storage.
- `write` overwrites an existing plan at the same slug without warning — slug collisions are caller responsibility.
- `resolve-slug` is pure path arithmetic; it does not stat or validate the slug.
- All audit emissions route through `mentat-log emit`; the skill never writes JSONL directly.
- `write` is atomic only at the OS level: a successful write emits `plan.succeeded`; an `OSError` emits `plan.failed` and propagates to the caller.
