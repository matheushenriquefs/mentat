"""Companion installer: 3rd-party skill suites mentat pairs with.

UX modeled on `npx skills@latest add <repo>` (matt-pocock's skill manager) —
Clack-style banner + boxed prompts + ASCII spinner. Pure stdlib (ADR-0008).
User confirms each interactively; --yes skips (assumes user already installed).
See .agents/skills/mentat-install/SKILL.md (Companion phase) for design rationale.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import threading
import time

_BANNER = "◆ mentat installer"
_PIPE = "│"
_PROMPT_OK = "◇"
_PROMPT_ASK = "◆"
_DONE = "✓"
_SKIP = "○"

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_ANSI_DIM = "\033[2m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"
_ANSI_RESET = "\033[0m"


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


def _color(text: str, ansi: str) -> str:
    if sys.stdout.isatty():
        return f"{ansi}{text}{_ANSI_RESET}"
    return text


def _print_banner() -> None:
    print()
    print(_color(_BANNER, _ANSI_GREEN))
    print(_color(_PIPE, _ANSI_DIM))


def _print_step(symbol: str, text: str, dim: bool = False) -> None:
    sym = _color(symbol, _ANSI_DIM if dim else _ANSI_GREEN)
    print(f"{sym}  {text}")
    print(_color(_PIPE, _ANSI_DIM))


def _prompt_yn(question: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    print(f"{_color(_PROMPT_ASK, _ANSI_YELLOW)}  {question}")
    raw = input(f"{_color(_PIPE, _ANSI_DIM)}  [{suffix}] ").strip().lower()
    print(_color(_PIPE, _ANSI_DIM))
    if not raw:
        return default
    return raw in ("y", "yes")


def _prompt_text(question: str, default: str) -> str:
    print(f"{_color(_PROMPT_ASK, _ANSI_YELLOW)}  {question}")
    print(f"{_color(_PIPE, _ANSI_DIM)}  default: {default}")
    raw = input(f"{_color(_PIPE, _ANSI_DIM)}  > ").strip()
    print(_color(_PIPE, _ANSI_DIM))
    return raw or default


class _Spinner:
    """ASCII spinner. Runs in background thread; stop() joins."""

    def __init__(self, label: str) -> None:
        self._label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> _Spinner:
        if sys.stdout.isatty():
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=0.2)
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def _loop(self) -> None:
        i = 0
        while not self._stop.is_set():
            frame = _SPINNER_FRAMES[i % len(_SPINNER_FRAMES)]
            sys.stdout.write(f"\r{_color(frame, _ANSI_YELLOW)}  {self._label}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)


def install_one(companion: dict, *, yes: bool) -> None:
    name = companion["name"]
    docs = companion["docs"]
    cmd_list = companion["install_cmd"]
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)

    if yes or _prompt_yn(f"Have you installed {name}?", default=True):
        _print_step(_SKIP, f"{name} (skipped — already installed)", dim=True)
        return

    print(f"{_color(_PIPE, _ANSI_DIM)}  docs: {docs}")
    edited_cmd = _prompt_text(f"Command to install {name}:", default=cmd_str)
    if not _prompt_yn(f"Run `{edited_cmd}`?", default=True):
        _print_step(_SKIP, f"{name} (skipped — user declined)", dim=True)
        return

    with _Spinner(f"installing {name}…"):
        result = subprocess.run(shlex.split(edited_cmd), check=False, capture_output=True, text=True)
    if result.returncode == 0:
        _print_step(_DONE, f"{name} installed")
    else:
        _print_step(_SKIP, f"{name} failed (exit {result.returncode}) — re-run manually", dim=True)


def install_all(*, yes: bool = False) -> int:
    if not sys.stdin.isatty() and not yes:
        return 0
    _print_banner()
    for companion in COMPANIONS:
        install_one(companion, yes=yes)
    return 0
