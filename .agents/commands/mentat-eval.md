---
description: Eval current SKILL.md vs main. Report a delta table.
---

$ARGUMENTS

From `skills/$ARGUMENTS/`:

1. Emit start: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-eval eval.start "{\"skill\":\"$ARGUMENTS\"}"`.
2. Functional: `bash eval/run.sh`.
2. Cognitive (current): `npx promptfoo eval --output /tmp/$ARGUMENTS-current.json --no-progress-bar`.
3. Cognitive (main): extract main's SKILL.md, override the prompt path:

```
   git show main:skills/$ARGUMENTS/SKILL.md > /tmp/main-SKILL.md
   npx promptfoo eval --prompts file:///tmp/main-SKILL.md --output /tmp/$ARGUMENTS-main.json --no-progress-bar
```

Report:

| Metric        | main | current | Δ |
| ------------- | ---- | ------- | - |
| pass rate     | …    | …       | … |
| prompt tokens | …    | …       | … |
| $/run         | …    | …       | … |

Include top 3 failing cases with the judge's reason, and the per-provider breakdown (does Haiku now clear 0.88?). Don't edit the skill.

Emit complete: `python3 ~/.agents/skills/mentat-log/scripts/log.py emit mentat-eval eval.complete "{\"skill\":\"$ARGUMENTS\"}"`.`
