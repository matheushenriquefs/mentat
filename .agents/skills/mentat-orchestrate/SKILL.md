---
name: mentat-orchestrate
description: >
  Fan out multiple plans in parallel, land them serially onto a holding branch.
  Use when you want to orchestrate a batch of plan slices across worktrees.
metadata:
  version: "0.1.0"
---

Hybrid orchestrator: one bin, three stage modules (`fan_out`, `land_queue`, `final_review`), four subcommands. Reads plan frontmatter to partition plans into anchored (HITL) and auto-spawned (AFK) groups. Spawns AFK plans in parallel via `ProcessPoolExecutor`; runs HITL plans in the current session. Lands all chunks serially onto the holding branch with gate checks.

## How to invoke

```
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py run [--harness <n>] [--model <s>] [--dry-run] <holding-branch> <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py fan-out <plan-ref>+
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py land-queue <holding-branch>
python3 ~/.agents/skills/mentat-orchestrate/scripts/orchestrate.py final-review <session>
```
