"""Claude Code harness adapter for mentat-implement."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


class Result:
    def __init__(self, returncode: int, session_log: Any = None) -> None:
        self.returncode = returncode
        self.session_log = session_log


def invoke(prompt: str, *, afk: bool, model: str | None) -> Result:
    """Invoke claude-code headless with the given prompt.

    Reads MENTAT_SESSION / MENTAT_SESSION_LOG from env (set by mentat-orchestrate
    fan_out). When both are set the run is captured: claude gets
    --session-id <id> + --output-format stream-json, and stdout is redirected
    into <session_log>. Result.session_log carries the path back so the
    self-answer detector and mentat-session track can read it.

    afk=True → --disallowedTools AskUserQuestion (AFK contract).
    """
    session_id = os.environ.get("MENTAT_SESSION")
    session_log_env = os.environ.get("MENTAT_SESSION_LOG")
    session_log = Path(session_log_env) if session_log_env else None

    cmd = ["claude", "--print", prompt]
    if session_id:
        cmd += ["--session-id", session_id]
    if session_log is not None:
        cmd += ["--output-format", "stream-json"]
    if afk:
        cmd += ["--disallowedTools", "AskUserQuestion"]
    if model:
        cmd += ["--model", model]

    if session_log is not None:
        session_log.parent.mkdir(parents=True, exist_ok=True)
        with session_log.open("wb") as fh:
            result = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE)
        return Result(returncode=result.returncode, session_log=session_log)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return Result(returncode=result.returncode, session_log=None)
