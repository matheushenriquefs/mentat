---
name: mentat-plan
description: >
  Write and manage mentat plan files.
  Use when the user wants to create a new plan, resolve a plan slug to a path,
  or write a plan body from a script.
metadata:
  version: "0.1.0"
---

Interactive plan-writing skill. Handles file IO, path canonicalization, and slug resolution. All bins that accept a plan reference use `mentat-plan resolve-slug` as the canonical resolver.

## How to invoke

```
python3 ~/.agents/skills/mentat-plan/scripts/plan.py [write <slug> <body-path>] [resolve-slug <ref>]
```

Default (no subcommand): interactive plan-writing mode.
