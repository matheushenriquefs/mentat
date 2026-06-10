---
name: mentat-skill
description: >
  Evaluate, shrink, or scaffold mentat skills.
  Use when you want to run promptfoo evals, propose a leaner SKILL.md, or create a new skill skeleton.
---

SKILL.md lifecycle workflows: eval against promptfoo, propose a leaner SKILL.md with gate-check, scaffold a new skill directory from template.

## How to invoke

```
python3 ~/.agents/skills/mentat-skill/scripts/skill.py eval [<skill-name>]
python3 ~/.agents/skills/mentat-skill/scripts/skill.py shrink [<skill-name>]
python3 ~/.agents/skills/mentat-skill/scripts/skill.py scaffold <new-skill-name>
```

Note: `eval` subcommand requires `promptfoo` binary on PATH. Install: `npm install -g promptfoo`.
