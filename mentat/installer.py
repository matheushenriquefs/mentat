"""Ask-and-run installer TUI. No detection. No dep schema.

See docs/INSTALLER.md for design rationale.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

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


def _print_header() -> None:
    print("\nmentat installer\n")


def _ask_confirm(prompt: str, default: bool = False) -> bool:
    if _HAS_QUESTIONARY:
        return questionary.confirm(prompt, default=default).ask()
    answer = input(f"{prompt} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def _ask_text(prompt: str, default: str = "") -> str:
    if _HAS_QUESTIONARY:
        return questionary.text(prompt, default=default).ask()
    shown = f"{prompt} [{default}] " if default else f"{prompt} "
    answer = input(shown).strip()
    return answer or default


def _install_companion(companion: dict, *, yes: bool) -> None:
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


def _install_mentat_skills(clone_root: Path | None = None) -> None:
    install_script = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-install/scripts/install.py"
    if not install_script.exists():
        print(f"mentat-installer: install script not found at {install_script}", file=sys.stderr)
        return
    subprocess.run([sys.executable, str(install_script), "--yes"], check=False)


def run_installer(*, yes: bool = False, dry_run: bool = False, clone_root: Path | None = None) -> int:
    _print_header()

    if dry_run:
        print("[dry-run] would prompt for companions and install skills.")
        return 0

    installed = 0
    for companion in COMPANIONS:
        _install_companion(companion, yes=yes)
        installed += 1

    _install_mentat_skills(clone_root)

    print(f"\nInstalled {installed} companion checks complete.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mentat-installer", description="Mentat ask-and-run installer")
    p.add_argument("--yes", "-y", action="store_true", help="Skip all confirmations (assume Yes to installed?)")
    p.add_argument("--dry-run", action="store_true", help="Print what would run; no exec")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    clone_root: Path | None = None
    cwd = Path.cwd()
    if (cwd / ".agents" / "skills").is_dir():
        clone_root = cwd

    sys.exit(run_installer(yes=args.yes, dry_run=args.dry_run, clone_root=clone_root))


if __name__ == "__main__":
    main()
