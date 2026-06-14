"""PATH setup: offer to add ~/.mentat/bin to the user's shell rc file.

UX matches companions.py — Clack-style prompts from lib.tui. Pure stdlib (ADR-0008).
Runs after companions, before "done". Skipped when --yes (assume PATH already set).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.tui import DONE, SKIP, open_tty, print_step, prompt_yn  # noqa: E402

_MENTAT_BIN = Path.home() / ".mentat" / "bin"
_EXPORT_LINE = 'export PATH="$HOME/.mentat/bin:$PATH"'

_SHELL_RC: dict[str, Path] = {
    "zsh": Path.home() / ".zshrc",
    "bash": Path.home() / ".bashrc",
    "fish": Path.home() / ".config" / "fish" / "config.fish",
}
_FISH_LINE = "fish_add_path $HOME/.mentat/bin"


def _detect_shell() -> str:
    shell_bin = os.environ.get("SHELL", "")
    name = Path(shell_bin).name
    return name if name in _SHELL_RC else "bash"


def _already_in_path() -> bool:
    return str(_MENTAT_BIN) in os.environ.get("PATH", "").split(":")


def _rc_has_mentat(rc: Path) -> bool:
    if not rc.exists():
        return False
    return ".mentat/bin" in rc.read_text()


def setup_path(*, yes: bool = False) -> None:
    if _already_in_path():
        print_step(SKIP, "~/.mentat/bin already in PATH — skipping", dim=True)
        return

    shell = _detect_shell()
    rc = _SHELL_RC[shell]

    if _rc_has_mentat(rc):
        print_step(SKIP, f"~/.mentat/bin already in {rc} — skipping", dim=True)
        return

    if yes:
        print_step(SKIP, f"~/.mentat/bin not in PATH — add manually to {rc}", dim=True)
        return

    with open_tty() as tty:
        if tty is None:
            print_step(SKIP, f"~/.mentat/bin not in PATH — add manually to {rc}", dim=True)
            return

        if not prompt_yn(f"Add ~/.mentat/bin to PATH in {rc}?", default=True, tty=tty):
            print_step(SKIP, "PATH not updated — add manually", dim=True)
            return

    line = _FISH_LINE if shell == "fish" else _EXPORT_LINE
    with rc.open("a") as f:
        f.write(f"\n# added by mentat-install\n{line}\n")

    print_step(DONE, f"added to {rc} — restart your shell or run: source {rc}")
