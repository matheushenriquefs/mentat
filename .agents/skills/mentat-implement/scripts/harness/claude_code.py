"""Claude Code harness adapter for mentat-implement."""

from __future__ import annotations

import subprocess
from typing import Any


class Result:
    def __init__(self, returncode: int, session_log: Any = None) -> None:
        self.returncode = returncode
        self.session_log = session_log


def invoke(prompt: str, *, afk: bool, model: str | None) -> Result:
    """Invoke claude-code headless with the given prompt.

    afk=True → --disallowedTools AskUserQuestion (AFK contract).
    """
    cmd = ["claude", "--headless", "--print", prompt]
    if afk:
        cmd += ["--disallowedTools", "AskUserQuestion"]
    if model:
        cmd += ["--model", model]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return Result(returncode=result.returncode)
