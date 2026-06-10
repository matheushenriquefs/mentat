---
name: mentat-implement
description: >
  Execute a single mentat plan atomically in the current session.
  Use when you want to implement one plan slice-by-slice with TDD, gates, and per-slice commits.
metadata:
  version: "0.1.0"
---

Atomic single-plan executor. Reads plan frontmatter, invokes the harness adapter (claude-code or cursor), runs TDD loop per slice, gates each slice, commits per slice. AFK plans run with `--disallowedTools AskUserQuestion`; HITL plans run interactively. Exits 42 if AFK ambiguity detected.

## How to invoke

```
python3 ~/.agents/skills/mentat-implement/scripts/implement.py <plan-ref> [--harness <name>]
```

`plan-ref`: bare slug (`my-plan`) or path (`~/.agents/plans/my-plan.md` or `/abs/path/plan.md`).
