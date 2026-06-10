"""Tests for mentat-git rebase submodule."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_rebase_ff_only():
    rebase_mod = load_module("rebase")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        rebase_mod.cmd_rebase(holding="main")

    assert calls
    cmd_str = " ".join(" ".join(str(c) for c in cmd) for cmd in calls)
    assert "rebase" in cmd_str.lower()


def test_rebase_refuses_non_ff_with_clear_error():
    rebase_mod = load_module("rebase")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=1, stderr="Not fast-forward")

    with patch("subprocess.run", fake_run), pytest.raises(SystemExit) as exc_info:
        rebase_mod.cmd_rebase(holding="main")
    assert exc_info.value.code != 0


def test_rebase_emits_no_audit_event():
    """rebase is silent — orchestrate emits land events."""
    rebase_mod = load_module("rebase")

    subprocess_calls = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        rebase_mod.cmd_rebase(holding="main")

    log_calls = [c for c in subprocess_calls if "log.py" in " ".join(str(x) for x in c)]
    assert not log_calls
