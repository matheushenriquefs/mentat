"""Tests for mentat-git diff submodule."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_diff_uses_config_tool_when_set(tmp_path, monkeypatch):
    diff_mod = load_module("diff")
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / ".mentat" / "config.jsonc"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"diff_tool": "difftastic"}')

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        diff_mod.cmd_diff(base="main")

    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("difftastic" in s for s in cmd_strs)


def test_diff_falls_back_to_git_diff_when_unset(tmp_path, monkeypatch):
    diff_mod = load_module("diff")
    monkeypatch.setenv("HOME", str(tmp_path))

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        diff_mod.cmd_diff(base="main")

    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("git" in s and "diff" in s for s in cmd_strs)
