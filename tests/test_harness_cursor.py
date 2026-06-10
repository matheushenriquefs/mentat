"""Tests for cursor harness adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

HARNESS_DIR = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/harness"


def load_module(name: str):
    path = HARNESS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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
