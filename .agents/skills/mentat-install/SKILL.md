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

## Flags

| Flag | Description |
|---|---|
| `--dry-run` | Preview only — no filesystem writes |
| `--yes` / `-y` | Skip confirmation prompt (assumes Yes to "have you installed?" companion checks) |
| `--no-color` | Disable ANSI color output |
| `--skip-companions` | Skip 3rd-party companion install prompts entirely |
| `--skip-path-setup` | Skip PATH setup prompt for `~/.mentat/bin` |
| `--help` / `-h` | Show usage |

## Companion phase

Prompts for two 3rd-party suites (matt-pocock-skills, juliusbrussee-caveman) via Clack-style stdlib TUI. Per companion: `[Y/n] Have you installed <name>?` → Yes skips, No shows docs URL + editable command + spinner-wrapped `subprocess.run`. Failures surface as `○ failed (exit N)`. `--yes` / `--skip-companions` short-circuit. Uses `/dev/tty` so `curl | bash` is interactive; no TTY → auto-skip.

## PATH setup phase

Prompts to add `~/.mentat/bin` to the shell rc file (`~/.zshrc`, `~/.bashrc`, fish). Skipped if already in `$PATH` or rc. Uses `/dev/tty` for `curl | bash`. `--yes` / `--skip-path-setup` skip.

## Runtime deps

Stdlib only (ADR-0008). Shared TUI helpers in `lib/tui.py`.
