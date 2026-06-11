"""Companion installer: 3rd-party skill suites mentat pairs with.

User confirms each interactively; --yes skips (assumes user already installed).
See .agents/skills/mentat-install/SKILL.md (Companion phase) for design rationale.
"""

from __future__ import annotations

import shlex
import subprocess
import sys

try:
    import questionary

    _HAS_QUESTIONARY = True
except ImportError:
    _HAS_QUESTIONARY = False


COMPANIONS: list[dict] = [
    {
        "name": "matt-pocock-skills",
        "docs": "https://github.com/mattpocock/skills",
        "install_cmd": ["npx", "-y", "skills@latest", "add", "mattpocock/skills", "--yes"],
    },
    {
        "name": "juliusbrussee-caveman",
        "docs": "https://github.com/JuliusBrussee/caveman",
        "install_cmd": [
            "bash",
            "-c",
            "curl -fsSL https://raw.githubusercontent.com/JuliusBrussee/caveman/main/install.sh | bash",
        ],
    },
]


def _ask_confirm(prompt: str, default: bool = False) -> bool:
    if _HAS_QUESTIONARY:
        return bool(questionary.confirm(prompt, default=default).ask())
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def _ask_text(prompt: str, default: str = "") -> str:
    if _HAS_QUESTIONARY:
        return str(questionary.text(prompt, default=default).ask() or default)
    shown = f"{prompt} [{default}] " if default else f"{prompt} "
    answer = input(shown).strip()
    return answer or default


def install_one(companion: dict, *, yes: bool) -> None:
    name = companion["name"]
    docs = companion["docs"]
    cmd_list = companion["install_cmd"]
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)

    if yes or _ask_confirm(f"Have you installed {name}?", default=True):
        return

    print(f"\nDocs: {docs}")
    print(f"Command: {cmd_str}\n")

    edited_cmd = _ask_text("Command to run:", default=cmd_str)
    if not _ask_confirm(f"Run `{edited_cmd}`?", default=True):
        print(f"Skipping {name}.")
        return

    subprocess.run(shlex.split(edited_cmd), check=False)


def install_all(*, yes: bool = False) -> int:
    if not sys.stdin.isatty() and not yes:
        return 0
    for companion in COMPANIONS:
        install_one(companion, yes=yes)
    return 0
