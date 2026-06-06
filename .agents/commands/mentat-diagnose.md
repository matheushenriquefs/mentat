---
description: Run the /diagnose loop inside the devcontainer, then hand the regression test off as the first red slice.
---

$ARGUMENTS

1. `/caveman ultra`.
2. `~/.agents/bin/mentat-container-up`.
3. `/diagnose`. Run every loop/probe/test via `~/.agents/bin/mentat-container-run '<cmd>'` — the deterministic signal lives container-side. Discover the test command from CLAUDE.md or AGENTS.md.
4. Diagnosis lands a regression test at a correct seam (or documents that no seam exists). Hand that off: it's the first red slice for `/to-plan` → `/to-implement`. If stopping here instead, `~/.agents/bin/mentat-container-down`.
