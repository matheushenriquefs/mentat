---
name: mentat-install
description: >
  Idempotent install of mentat skills and user state directories.
  Use when setting up mentat on a new machine or after pulling updates.
metadata:
  version: "0.1.0"
---

Idempotent install: creates `~/.mentat/` state dirs, symlinks (clone mode) or copies (user-install mode) skill dirs to `~/.agents/skills/`, creates per-harness symlinks for detected harnesses (`~/.claude/`, `~/.cursor/`), reports stale paths.

## How to invoke

```
.agents/bin/mentat-install [--dry-run] [--yes] [--no-color] [--help]
```

or directly:

```
python3 ~/.agents/skills/mentat-install/scripts/install.py [--dry-run] [--yes] [--no-color] [--help]
```

## Flags

| Flag | Description |
|---|---|
| `--dry-run` | Preview only — no filesystem writes |
| `--yes` / `-y` | Skip confirmation prompt |
| `--no-color` | Disable ANSI color output |
| `--help` / `-h` | Show usage |
