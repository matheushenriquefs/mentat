"""Cursor harness adapter for mentat-implement."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from harness import Result

_AFK_SYSTEM_CLAUSE = (
    "[AFK MODE: make autonomous decisions, do not ask the user questions, "
    "do not use interactive prompts, proceed without confirmation]"
)


def invoke(
    prompt: str,
    *,
    afk: bool,
    model: str | None,
    seed_summary: str | None = None,
) -> Result:
    """Invoke cursor-agent headless with the given prompt.

    cursor-agent CLI shape (verified 2026-06-11):
      binary: cursor-agent
      headless: --print
      capture: --output-format stream-json (when session_log set)
      model: --model <model>
      no --session-id (cursor uses internal chat IDs, not mentat session IDs)
      no --disallowedTools (inject AFK clause into prompt prefix instead)

    Reads MENTAT_SESSION_LOG from env (set by mentat-orchestrate fan_out).
    When set, stdout is redirected into <session_log>. Result.session_log
    carries the path back so the self-answer detector and mentat-session
    track can read it.

    seed_summary → prepended to prompt for seeded fresh-session continuity (F4).
    usage_tokens → always None for cursor (no CLI usage-reporting equivalent yet).
    """
    session_log_env = os.environ.get("MENTAT_SESSION_LOG")
    session_log = Path(session_log_env) if session_log_env else None

    prefix = ""
    if afk:
        prefix += f"{_AFK_SYSTEM_CLAUSE}\n\n"
    if seed_summary:
        prefix += f"{seed_summary}\n\n"
    full_prompt = f"{prefix}{prompt}" if prefix else prompt

    cmd = ["cursor-agent", "--print", "--trust", full_prompt]
    if session_log is not None:
        cmd += ["--output-format", "stream-json"]
    if model:
        cmd += ["--model", model]

    if session_log is not None:
        session_log.parent.mkdir(parents=True, exist_ok=True)
        with session_log.open("wb") as fh:
            result = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE)
        return Result(returncode=result.returncode, session_log=session_log, usage_tokens=None)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return Result(returncode=result.returncode, session_log=None, usage_tokens=None)
