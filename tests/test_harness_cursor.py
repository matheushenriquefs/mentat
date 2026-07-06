"""Tests for cursor harness adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

HARNESS_DIR = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/harness"


def load_module(name: str):
    return load_script(HARNESS_DIR / f"{name}.py", name)


def test_cursor_adapter_mirrors_afk_contract():
    """cursor adapter must restrict tools when afk=True, same as claude_code."""
    cursor = load_module("cursor")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        cursor.invoke("do the thing", afk=True, model=None)

    # cursor adapter must emit some form of tool restriction for AFK
    assert calls, "no subprocess call made"
    cmd_str = " ".join(str(c) for c in calls[0])
    # The adapter should encode AFK somehow — either flag or env
    assert (
        "AskUserQuestion" in cmd_str
        or "disallowed" in cmd_str.lower()
        or "--no-interactive" in cmd_str
        or "afk" in cmd_str.lower()
    )


def test_invoke_uses_cursor_agent_binary(monkeypatch):
    cursor = load_module("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert captured["cmd"][0] == "cursor-agent", f"binary must be cursor-agent, got {captured['cmd'][0]!r}"


def test_invoke_cursor_no_headless_flag(monkeypatch):
    cursor = load_module("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert "--headless" not in captured["cmd"], f"--headless must not be in cmd: {captured['cmd']}"
    assert "--print" in captured["cmd"], f"--print must be in cmd: {captured['cmd']}"


def test_invoke_cursor_no_session_id_flag(monkeypatch):
    cursor = load_module("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.setenv("MENTAT_AGENT", "test-session-123")
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert "--session-id" not in captured["cmd"], f"--session-id not supported by cursor-agent: {captured['cmd']}"


def test_invoke_cursor_no_disallowed_tools_flag(monkeypatch):
    cursor = load_module("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)

    cursor.invoke("hi", afk=True, model=None)

    assert "--disallowedTools" not in captured["cmd"], (
        f"--disallowedTools not supported by cursor-agent: {captured['cmd']}"
    )


def test_invoke_cursor_model_flag(monkeypatch):
    cursor = load_module("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_AGENT", raising=False)
    monkeypatch.delenv("MENTAT_AGENT_LOG", raising=False)

    cursor.invoke("hi", afk=False, model="claude-sonnet-4-6")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-sonnet-4-6"
