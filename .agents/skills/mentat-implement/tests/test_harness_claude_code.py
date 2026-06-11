"""Slice A: claude_code adapter must not use --headless."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "harness"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_invoke_no_headless_flag(monkeypatch):
    claude_code = _load("claude_code")
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
    claude_code = _load("claude_code")
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
    claude_code = _load("claude_code")
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
