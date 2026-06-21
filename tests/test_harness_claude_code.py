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


def test_invoke_no_headless_flag(monkeypatch):
    claude_code = load_module("claude_code")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    claude_code.invoke("hi", afk=False, model=None)

    assert "--headless" not in captured["cmd"], f"--headless must not be in cmd: {captured['cmd']}"
    assert "--print" in captured["cmd"], f"--print must be in cmd: {captured['cmd']}"


def test_invoke_afk_adds_disallowed_tools(monkeypatch):
    claude_code = load_module("claude_code")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    claude_code.invoke("hi", afk=True, model=None)

    assert "--disallowedTools" in captured["cmd"]
    idx = captured["cmd"].index("--disallowedTools")
    assert captured["cmd"][idx + 1] == "AskUserQuestion"


def test_invoke_model_flag(monkeypatch):
    claude_code = load_module("claude_code")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    claude_code.invoke("hi", afk=False, model="claude-opus-4-7")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-opus-4-7"
