---
description: Scaffold a new skill with promptfoo wiring and live symlink.
---

$ARGUMENTS

1. `/caveman ultra`.
2. Use `skill-creator` to draft `skills/$ARGUMENTS/SKILL.md`.
3. Copy `@context/promptfoo-template.yaml` to `skills/$ARGUMENTS/promptfooconfig.yaml`. Derive 10 diverse test inputs from the SKILL.md.
4. `ln -sfn $PWD/skills/$ARGUMENTS ~/.claude/skills/$ARGUMENTS`.

Don't run evals.
