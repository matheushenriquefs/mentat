---
description: Plan a change. Grill, slice into tracer bullets, then write a plan file.
---

$ARGUMENTS

1. `/caveman ultra`.
2. `/grill-with-docs`.
3. Split into **tracer-bullet vertical slices** — thin cuts through every layer end-to-end, each verifiable alone, many-thin over few-thick. Tag each **AFK** (gate clears unattended → orchestratable) or **HITL** (needs an architectural/design call). Note blocked-by between slices. The slice is the orchestration unit: a clean vertical cut is why parallel chunks compose instead of colliding. If the slices form ≥2 groups with disjoint write-sets and no chain between groups, emit one sibling plan per group plus a parent index file; otherwise emit one plan.
4. Write the plan to `~/.agents/plans/<slug>.md` and report the path.
