"""Tests for claude-code harness adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

HARNESS_DIR = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/harness"


def load_module(name: str):
    return load_script(HARNESS_DIR / f"{name}.py", name)


def test_claude_code_adapter_afk_disallows_questions():
    cc = load_module("claude_code")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        cc.invoke("do the thing", afk=True, model=None)

    assert calls
    cmd = calls[0]
    cmd_str = " ".join(str(c) for c in cmd)
    assert "AskUserQuestion" in cmd_str or "disallowedTools" in cmd_str or "--disallowed" in cmd_str


def test_claude_code_adapter_hitl_allows_questions():
    cc = load_module("claude_code")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        cc.invoke("do the thing", afk=False, model=None)

    assert calls
    cmd = calls[0]
    cmd_str = " ".join(str(c) for c in cmd)
    assert "AskUserQuestion" not in cmd_str or "disallowedTools" not in cmd_str
