# Installer TUI

`mentat/installer.py` — ask-and-run installer. No detection. No dep schema.

## Library

`questionary` (prompt_toolkit-based): `confirm`, `text`, `select`, `checkbox`.
Single PyPI dep. Closest Python equivalent to Node `@clack/prompts`.

## Companions

Two hardcoded companions in `COMPANIONS`:

```python
COMPANIONS = [
    {
        "name": "matt-pocock-skills",
        "docs": "https://github.com/mattpocock/skills",
        "install_cmd": ["npx", "-y", "skills@latest", "add", "mattpocock/skills", "--yes"],
    },
    {
        "name": "juliusbrussee-caveman",
        "docs": "https://github.com/JuliusBrussee/caveman",
        "install_cmd": ["bash", "-c", "curl -fsSL https://raw.githubusercontent.com/JuliusBrussee/caveman/main/install.sh | bash"],
    },
]
```

## Flow

1. Header banner: chip + "mentat installer".
2. For each companion (matt, then julius):
   1. `questionary.confirm("Have you installed <name>?")`.
   2. Yes → skip to next.
   3. No → print docs URL + install command.
      `questionary.text("Command to run:", default=<cmd>)` lets user edit.
      `questionary.confirm("Run `<edited>`?")`.
   4. Confirmed → `subprocess.run(shlex.split(edited), check=False)` streams to terminal.
   5. After exit (success or fail): resume to next companion. No retry — user re-runs if needed.
3. After both companions: install mentat skills (symlinks, `~/.mentat/` dirs, default config).
4. Final "Installed N items" summary.

## Flags

| Flag | Meaning |
|---|---|
| `--yes` | Skip all confirmations; assume Yes to "installed?" → skips companion install |
| `--dry-run` | Print what would run; do not exec or symlink |
| `--help` | Usage |

No `--skip-companions` — user says Yes individually to skip. No `--no-color` — questionary handles TTY.

## Risk note

`bash -c curl | bash` for juliusbrussee-caveman is a known supply-chain risk. User
explicitly confirms via `questionary.confirm` before exec. Safer alternative:
`npx -y skills add JuliusBrussee/caveman` (no remote bash exec; shown in docs).

## Exec model

```python
subprocess.run(shlex.split(edited_cmd), check=False)
```

`check=False` — installer continues to next companion regardless of exit code.
User re-runs if a companion install failed mid-stream.
