---
name: mentat-install
description: >
  Idempotent install of mentat skills and user state directories.
  Use when setting up mentat on a new machine or after pulling updates.
---

Idempotent install: creates `~/.mentat/` state dirs, symlinks (clone mode) or copies (user-install mode) skill dirs to `~/.agents/skills/`, creates per-harness symlinks for detected harnesses (`~/.claude/`, `~/.cursor/`), ships ADRs via `~/.agents/docs/adr` symlink, reports stale paths. Interactively prompts for 3rd-party companions (matt-pocock-skills, caveman) — see `scripts/companions.py`.

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
| `--yes` / `-y` | Skip confirmation prompt (assumes Yes to "have you installed?" companion checks) |
| `--no-color` | Disable ANSI color output |
| `--skip-companions` | Skip 3rd-party companion install prompts entirely |
| `--help` / `-h` | Show usage |

## Companion phase

Before symlink work, prompts for two 3rd-party suites (matt-pocock-skills, juliusbrussee-caveman). Per companion: `questionary.confirm("Have you installed <name>?")` → Yes skips, No shows docs URL + editable command, then optional `subprocess.run` of the edited command. `check=False` — failures don't abort. `--yes` / `--skip-companions` short-circuit. No TTY → auto-skip. Soft-imports `questionary`; falls back to `input()` if absent. See `scripts/companions.py` for the COMPANIONS list.

## Runtime deps

Stdlib only at the bin layer (ADR-0008). `questionary` is an optional UX upgrade for the companion phase — install via `pip install --user questionary` if richer prompts are desired; otherwise plain `input()` works.
