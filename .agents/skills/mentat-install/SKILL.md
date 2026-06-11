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

Before symlink work, prompts for two 3rd-party suites (matt-pocock-skills, juliusbrussee-caveman) via a Clack-style stdlib TUI (banner + boxed prompts + ASCII spinner) modeled on `npx skills@latest add` ground truth. Per companion: `[Y/n] Have you installed <name>?` → Yes skips, No shows docs URL + editable command + spinner-wrapped `subprocess.run`. `check=False` — failures don't abort, surface as `○ failed (exit N) — re-run manually`. `--yes` / `--skip-companions` short-circuit. No TTY → auto-skip. See `scripts/companions.py` for the COMPANIONS list.

## Runtime deps

Stdlib only at the bin layer (ADR-0008). No third-party dependencies — no `questionary`, no `rich`. Pure `input()` + ANSI escape sequences + threading for the spinner.
