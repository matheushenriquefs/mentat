"""Recovery agent decision: parse JSON action from model reply."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

RETRY = "retry"
RESLICE = "reslice"
ABANDON = "abandon"
_ACTIONS = frozenset({RETRY, RESLICE, ABANDON})


def _extract_json(raw: str) -> str:
    """Slice the first balanced ``{...}`` object out of a possibly-chatty reply."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in reply")
    return raw[start : end + 1]


def parse_decision(raw: str) -> dict[str, str]:
    """Parse the agent reply into ``{action, rationale}``.

    Any unparseable reply or unrecognized action degrades to ``abandon`` — the
    safe escalate rung (never a blind retry against an unclassifiable failure)."""
    try:
        obj = json.loads(_extract_json(raw))
    except json.JSONDecodeError, ValueError:
        return {"action": ABANDON, "rationale": "unparseable recovery decision"}
    action = obj.get("action")
    if action not in _ACTIONS:
        return {"action": ABANDON, "rationale": f"unrecognized recovery action {action!r}"}
    return {"action": action, "rationale": str(obj.get("rationale", ""))}


def invoke_claude(prompt: str, *, subprocess_mod: Any | None = None) -> str:
    """Run the recovery agent headless (claude --print, AFK-safe) and return stdout.

    A non-zero exit or launch failure yields an empty string, which
    ``parse_decision`` turns into a safe ``abandon``."""
    sp = subprocess if subprocess_mod is None else subprocess_mod
    cmd = ["claude", "--print", prompt, "--dangerously-skip-permissions", "--disallowedTools", "AskUserQuestion"]
    try:
        result = sp.run(cmd, capture_output=True, text=True)
    except OSError:
        return ""
    return result.stdout if result.returncode == 0 else ""


def decide(
    context: dict[str, object],
    *,
    invoke: Callable[[str], str] | None = None,
    prompt_fn: Callable[[dict[str, object]], str] | None = None,
    subprocess_mod: Any | None = None,
) -> dict[str, str]:
    """Ask the recovery agent how to recover a chunk. Returns ``{action, rationale}``."""
    if prompt_fn is None:
        raise ValueError("decide requires prompt_fn")
    invoke = invoke or (lambda p: invoke_claude(p, subprocess_mod=subprocess_mod))
    return parse_decision(invoke(prompt_fn(context)))
