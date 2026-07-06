"""F4: fresh-agent-over-compact spike — usage reporting + seeded spawn.

Red tracers:
- Result.usage_tokens attribute exists on both adapters (int | None)
- claude_code adapter parses usage from stream-json log after run
- invoke() accepts seed_summary param on both adapters
- cursor adapter returns usage_tokens=None (no CLI equivalent yet)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

HARNESS_DIR = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/harness"


def load_module(name: str):
    return load_script(HARNESS_DIR / f"{name}.py", name)


# ── Result.usage_tokens ───────────────────────────────────────────────────────


def test_claude_code_result_has_usage_tokens() -> None:
    """F4 tracer: claude_code.Result must have usage_tokens attribute."""
    cc = load_module("claude_code")
    r = cc.Result(returncode=0)
    assert hasattr(r, "usage_tokens"), "claude_code.Result missing usage_tokens"


def test_cursor_result_has_usage_tokens() -> None:
    """F4 tracer: cursor.Result must have usage_tokens attribute (may be None)."""
    cursor = load_module("cursor")
    r = cursor.Result(returncode=0)
    assert hasattr(r, "usage_tokens"), "cursor.Result missing usage_tokens"


# ── seed_summary parameter ────────────────────────────────────────────────────


def test_claude_code_invoke_accepts_seed_summary() -> None:
    """F4 tracer: invoke() must accept seed_summary kwarg without error."""
    cc = load_module("claude_code")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        result = cc.invoke("do the thing", afk=False, model=None, seed_summary="prior context")
    assert result.returncode == 0


def test_cursor_invoke_accepts_seed_summary() -> None:
    """F4 tracer: cursor invoke() must accept seed_summary kwarg without error."""
    cursor = load_module("cursor")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        result = cursor.invoke("do the thing", afk=False, model=None, seed_summary="prior context")
    assert result.returncode == 0


# ── usage parsed from stream-json log ────────────────────────────────────────


def test_claude_code_parses_usage_from_stream_json(tmp_path: Path) -> None:
    """F4 tracer: after a run with agent_log, usage_tokens is populated from the log."""
    import os

    cc = load_module("claude_code")

    log = tmp_path / "transcript.jsonl"
    result_event = {
        "type": "result",
        "result": "done",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    log_line = (json.dumps(result_event) + "\n").encode()

    def fake_run(cmd, **kwargs):
        # adapter opens agent_log with "wb" and passes fh as stdout;
        # write the fake event so _parse_usage can read it after the run
        fh = kwargs.get("stdout")
        if fh is not None:
            fh.write(log_line)
        return MagicMock(returncode=0)

    env = {**os.environ, "MENTAT_AGENT_LOG": str(log)}
    with patch("subprocess.run", fake_run), patch.dict("os.environ", env, clear=False):
        result = cc.invoke("do the thing", afk=False, model=None)

    assert result.usage_tokens == 150, f"expected 150 (in+out), got {result.usage_tokens}"


def test_cursor_returns_none_for_usage_tokens() -> None:
    """F4 tracer: cursor adapter returns usage_tokens=None (no CLI equivalent)."""
    cursor = load_module("cursor")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        result = cursor.invoke("do the thing", afk=False, model=None)

    assert result.usage_tokens is None, f"expected None for cursor usage_tokens, got {result.usage_tokens}"
