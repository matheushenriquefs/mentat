"""Clack-style stdlib TUI helpers: color, prompts, TTY context manager.

Shared between mentat-install skill scripts. Pure stdlib (ADR-0008).
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Generator
from typing import IO

PIPE = "│"
PROMPT_ASK = "◆"
DONE = "✓"
SKIP = "○"
EJECTED = "✗"

_ANSI_DIM = "\033[2m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"

# Exported palette handle for consumers (the tracker) that pass an SGR code to color().
DIM = _ANSI_DIM
# Clear screen + move cursor home — the tracker repaints in place each tick.
CLEAR_HOME = "\033[2J\033[H"

# ── S7 tracking vocabulary ────────────────────────────────────────────────────
# Single-width glyphs drawn from the house set so the install/prompt UI and the
# live tracker share one look. No emoji.
_TOOL_GLYPHS = {
    "Read": "·",
    "Edit": "~",
    "Write": "+",
    "Bash": "$",
    "Grep": "/",
    "Glob": "/",
    "Task": "»",
}
_LIFECYCLE_GLYPHS = {
    "spawned": "+",
    "landed": DONE,
    "ejected": EJECTED,
    "hitl": PROMPT_ASK,
    "commit": "●",
}
# List-pane status palette — reuses the (rank) colors: waiting yellow, idle green,
# working red-ish/active, ? dim.
_STATUS_ANSI = {
    "waiting": _ANSI_YELLOW,
    "idle": _ANSI_GREEN,
    "working": _ANSI_RED,
    "?": _ANSI_DIM,
}


def color(text: str, ansi: str) -> str:
    if sys.stdout.isatty():
        return f"{ansi}{text}{_ANSI_RESET}"
    return text


def tool_glyph(name: str) -> str:
    """Single-width glyph for a harness tool call (· for anything unmapped)."""
    return _TOOL_GLYPHS.get(name, "·")


def lifecycle_glyph(name: str) -> str:
    """Single-width glyph for an AFK lifecycle event (· for anything unmapped)."""
    return _LIFECYCLE_GLYPHS.get(name, "·")


def status_color(status: str) -> str:
    """ANSI SGR code for a session status (dim fallback for unknown)."""
    return _STATUS_ANSI.get(status, _ANSI_DIM)


def status_dot(status: str) -> str:
    """A `●` colored by session status (plain when not a tty)."""
    return color("●", status_color(status))


def section_rule(label: str) -> str:
    """A `── [label] ──` section rule, the per-session header in the tracker."""
    return f"── [{label}] ──"


def print_step(symbol: str, text: str, dim: bool = False) -> None:
    sym = color(symbol, _ANSI_DIM if dim else _ANSI_GREEN)
    print(f"{sym}  {text}")
    print(color(PIPE, _ANSI_DIM))


@contextlib.contextmanager
def open_tty() -> Generator[IO[str] | None, None, None]:
    """Yield a readable file for interactive input, even inside curl | bash.

    Yields None when no TTY is available (true non-interactive CI).
    Closes /dev/tty on exit; never closes sys.stdin.
    """
    if sys.stdin.isatty():
        yield sys.stdin
        return
    try:
        tty = open("/dev/tty")  # noqa: SIM115
    except OSError:
        yield None
        return
    try:
        yield tty
    finally:
        tty.close()


def prompt_yn(question: str, default: bool, *, tty: IO[str]) -> bool:
    suffix = "Y/n" if default else "y/N"
    print(f"{color(PROMPT_ASK, _ANSI_YELLOW)}  {question}")
    sys.stdout.write(f"{color(PIPE, _ANSI_DIM)}  [{suffix}] ")
    sys.stdout.flush()
    raw = tty.readline().strip().lower()
    print(color(PIPE, _ANSI_DIM))
    if not raw:
        return default
    return raw in ("y", "yes")


def prompt_text(question: str, default: str, *, tty: IO[str]) -> str:
    print(f"{color(PROMPT_ASK, _ANSI_YELLOW)}  {question}")
    print(f"{color(PIPE, _ANSI_DIM)}  default: {default}")
    sys.stdout.write(f"{color(PIPE, _ANSI_DIM)}  > ")
    sys.stdout.flush()
    raw = tty.readline().strip()
    print(color(PIPE, _ANSI_DIM))
    return raw or default
