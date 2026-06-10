---
name: mentat-log
description: >
  Emit, validate, query, and prune mentat audit log entries.
  Use when the user wants to inspect orchestration history, debug a failed batch,
  or write a custom event from a script.
metadata:
  version: "0.1.0"
---

Emit, validate, query, and prune structured JSONL audit entries under `~/.mentat/logs/`. Owns the canonical `EVENT_CATALOG` — the single source of truth for the 9 event types that all mentat skills emit.

## How to invoke

```
python3 ~/.agents/skills/mentat-log/scripts/log.py <subcommand> <args>
```

Subcommands: `emit`, `validate`, `query`, `prune`.
