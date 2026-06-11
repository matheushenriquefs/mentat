"""Slice B: cursor adapter must use cursor-agent with correct flags."""

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


def test_invoke_uses_cursor_agent_binary(monkeypatch):
    cursor = _load("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert captured["cmd"][0] == "cursor-agent", f"binary must be cursor-agent, got {captured['cmd'][0]!r}"


def test_invoke_no_headless_flag(monkeypatch):
    cursor = _load("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert "--headless" not in captured["cmd"], f"--headless must not be in cmd: {captured['cmd']}"
    assert "--print" in captured["cmd"], f"--print must be in cmd: {captured['cmd']}"


def test_invoke_no_session_id_flag(monkeypatch):
    cursor = _load("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.setenv("MENTAT_SESSION", "test-session-123")
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    cursor.invoke("hi", afk=False, model=None)

    assert "--session-id" not in captured["cmd"], f"--session-id not supported by cursor-agent: {captured['cmd']}"


def test_invoke_no_disallowed_tools_flag(monkeypatch):
    cursor = _load("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    cursor.invoke("hi", afk=True, model=None)

    assert "--disallowedTools" not in captured["cmd"], (
        f"--disallowedTools not supported by cursor-agent: {captured['cmd']}"
    )


def test_invoke_model_flag(monkeypatch):
    cursor = _load("cursor")
    captured: dict = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return FakeResult()

    monkeypatch.setattr(cursor.subprocess, "run", fake_run)
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.delenv("MENTAT_SESSION_LOG", raising=False)

    cursor.invoke("hi", afk=False, model="claude-sonnet-4-6")

    assert "--model" in captured["cmd"]
    idx = captured["cmd"].index("--model")
    assert captured["cmd"][idx + 1] == "claude-sonnet-4-6"
