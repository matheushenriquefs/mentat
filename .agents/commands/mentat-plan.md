---
description: Plan a change. Grill, slice into tracer bullets, then write a plan file.
---

$ARGUMENTS

1. Derive `$plan_path = ~/.agents/plans/<slug>.md` from the slug you'll use in step 5 (slugify `$ARGUMENTS`'s subject) — this is the artifact lineage key. Then emit start: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-plan plan.start "{\"path\":\"$plan_path\"}"`.
2. `/caveman ultra`.
3. `/grill-with-docs`.
4. Split into **tracer-bullet vertical slices** — thin cuts through every layer end-to-end, each verifiable alone, many-thin over few-thick. Tag each **AFK** (gate clears unattended → orchestratable) or **HITL** (needs an architectural/design call). Note blocked-by between slices. The slice is the orchestration unit: a clean vertical cut is why parallel chunks compose instead of colliding. If the slices form ≥2 groups with disjoint write-sets and no chain between groups, emit one sibling plan per group plus a parent index file; otherwise emit one plan.
5. Write the plan to `$plan_path` and report the path.
6. Emit complete: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-plan plan.complete "{\"path\":\"$plan_path\"}"`.`
