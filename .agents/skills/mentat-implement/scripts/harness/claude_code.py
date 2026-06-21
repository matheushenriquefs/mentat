"""Claude Code harness adapter for mentat-implement."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from harness import Result


def _parse_usage(log_path: Path) -> int | None:
    """Parse total tokens (input + output) from a stream-json session log."""
    try:
        for line in log_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                usage = event.get("usage", {})
                input_t = usage.get("input_tokens", 0)
                output_t = usage.get("output_tokens", 0)
                return input_t + output_t
    except OSError:
        pass
    return None


def invoke(
    prompt: str,
    *,
    afk: bool,
    model: str | None,
    seed_summary: str | None = None,
) -> Result:
    """Invoke claude-code headless with the given prompt.

    Reads MENTAT_SESSION_LOG from env (set by mentat-orchestrate fan_out). When
    set the run is captured: claude gets --output-format stream-json --verbose,
    and stdout is redirected into <session_log>. Result.session_log carries the
    path back so the self-answer detector and mentat-session track can read it.

    afk=True → --disallowedTools AskUserQuestion (AFK contract).
    seed_summary → prepended to prompt for seeded fresh-session continuity.
    usage_tokens → parsed from stream-json log after run (input + output total).
    """
    session_log_env = os.environ.get("MENTAT_SESSION_LOG")
    session_log = Path(session_log_env) if session_log_env else None

    full_prompt = f"{seed_summary}\n\n{prompt}" if seed_summary else prompt

    cmd = ["claude", "--print", full_prompt]
    if afk:
        cmd += ["--dangerously-skip-permissions", "--disallowedTools", "AskUserQuestion"]
    if session_log is not None:
        cmd += ["--output-format", "stream-json", "--verbose"]
    if model:
        cmd += ["--model", model]

    if session_log is not None:
        session_log.parent.mkdir(parents=True, exist_ok=True)
        with session_log.open("wb") as fh:
            result = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE)
        usage = _parse_usage(session_log)
        return Result(returncode=result.returncode, session_log=session_log, usage_tokens=usage)

    result = subprocess.run(cmd, capture_output=True, text=True)
    return Result(returncode=result.returncode, session_log=None, usage_tokens=None)
