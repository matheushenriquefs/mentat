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
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.tui import DONE, PIPE, SKIP, color, open_tty, print_step, prompt_text, prompt_yn  # noqa: E402

_BANNER = "◆ mentat installer"
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

_ANSI_DIM = "\033[2m"
_ANSI_GREEN = "\033[32m"
_ANSI_YELLOW = "\033[33m"


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


def _print_banner() -> None:
    print()
    print(color(_BANNER, _ANSI_GREEN))
    print(color(PIPE, _ANSI_DIM))


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
            sys.stdout.write(f"\r{color(frame, _ANSI_YELLOW)}  {self._label}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.08)


def install_one(companion: dict, *, tty) -> None:
    name = companion["name"]
    docs = companion["docs"]
    cmd_list = companion["install_cmd"]
    cmd_str = " ".join(shlex.quote(c) for c in cmd_list)

    if prompt_yn(f"Have you installed {name}?", default=True, tty=tty):
        print_step(SKIP, f"{name} (skipped — already installed)", dim=True)
        return

    print(f"{color(PIPE, _ANSI_DIM)}  docs: {docs}")
    edited_cmd = prompt_text(f"Command to install {name}:", default=cmd_str, tty=tty)
    if not prompt_yn(f"Run `{edited_cmd}`?", default=True, tty=tty):
        print_step(SKIP, f"{name} (skipped — user declined)", dim=True)
        return

    with _Spinner(f"installing {name}…"):
        result = subprocess.run(shlex.split(edited_cmd), check=False, capture_output=True, text=True)
    if result.returncode == 0:
        print_step(DONE, f"{name} installed")
    else:
        print_step(SKIP, f"{name} failed (exit {result.returncode}) — re-run manually", dim=True)


def install_all(*, yes: bool = False) -> int:
    if yes:
        return 0
    with open_tty() as tty:
        if tty is None:
            return 0
        _print_banner()
        for companion in COMPANIONS:
            install_one(companion, tty=tty)
    return 0
