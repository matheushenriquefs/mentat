"""PATH setup: offer to add ~/.mentat/bin to the user's shell rc file.

UX matches companions.py — Clack-style prompts, same symbols. Pure stdlib (ADR-0008).
Runs after companions, before "done". Skipped when --yes (assume PATH already set).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PIPE = "│"
_PROMPT_ASK = "◆"
_DONE = "✓"
_SKIP = "○"

_ANSI_DIM = "\033[2m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RESET = "\033[0m"

_MENTAT_BIN = Path.home() / ".mentat" / "bin"
_EXPORT_LINE = 'export PATH="$HOME/.mentat/bin:$PATH"'

_SHELL_RC: dict[str, Path] = {
    "zsh": Path.home() / ".zshrc",
    "bash": Path.home() / ".bashrc",
    "fish": Path.home() / ".config" / "fish" / "config.fish",
}
_FISH_LINE = "fish_add_path $HOME/.mentat/bin"


def _color(text: str, ansi: str) -> str:
    if sys.stdout.isatty():
        return f"{ansi}{text}{_ANSI_RESET}"
    return text


def _print_step(symbol: str, text: str, dim: bool = False) -> None:
    sym = _color(symbol, _ANSI_DIM if dim else _ANSI_GREEN)
    print(f"{sym}  {text}")
    print(_color(_PIPE, _ANSI_DIM))


def _open_tty():
    """Return a readable file for interactive input, even inside curl | bash."""
    if sys.stdin.isatty():
        return sys.stdin
    try:
        return open("/dev/tty")  # noqa: SIM115
    except OSError:
        return None


def _prompt_yn(question: str, default: bool, *, tty) -> bool:
    suffix = "Y/n" if default else "y/N"
    print(f"{_color(_PROMPT_ASK, _ANSI_YELLOW)}  {question}")
    sys.stdout.write(f"{_color(_PIPE, _ANSI_DIM)}  [{suffix}] ")
    sys.stdout.flush()
    raw = tty.readline().strip().lower()
    print(_color(_PIPE, _ANSI_DIM))
    if not raw:
        return default
    return raw in ("y", "yes")


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
        _print_step(_SKIP, "~/.mentat/bin already in PATH — skipping", dim=True)
        return

    shell = _detect_shell()
    rc = _SHELL_RC[shell]

    if _rc_has_mentat(rc):
        _print_step(_SKIP, f"~/.mentat/bin already in {rc} — skipping", dim=True)
        return

    if yes:
        _print_step(_SKIP, f"~/.mentat/bin not in PATH — add manually to {rc}", dim=True)
        return

    tty = _open_tty()
    if tty is None:
        _print_step(_SKIP, f"~/.mentat/bin not in PATH — add manually to {rc}", dim=True)
        return

    if not _prompt_yn(f"Add ~/.mentat/bin to PATH in {rc}?", default=True, tty=tty):
        _print_step(_SKIP, "PATH not updated — add manually", dim=True)
        return

    line = _FISH_LINE if shell == "fish" else _EXPORT_LINE
    with rc.open("a") as f:
        f.write(f"\n# added by mentat-install\n{line}\n")

    _print_step(_DONE, f"added to {rc} — restart your shell or run: source {rc}")
