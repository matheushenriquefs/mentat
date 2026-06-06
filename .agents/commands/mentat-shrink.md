---
description: Propose a leaner skill prompt. Gate against main. Commit and rebase if it passes.
---

$ARGUMENTS

1. `/caveman ultra`.
2. Read `skills/$ARGUMENTS/SKILL.md`. Identify the 3 highest-token sections (examples, edge-case enumerations, redundant phrasing). Rewrite each to preserve intent in fewer tokens.
3. Run `/mentat-eval $ARGUMENTS`. Gate: pass rate ≥ 0.88 AND tokens ≤ 1.10× main.

- Pass → `/mentat-commit`, then `/mentat-rebase <holding-branch>`. Ask the user for the holding-branch name if not specified.
- Fail → revert the SKILL.md and report which axis failed.
