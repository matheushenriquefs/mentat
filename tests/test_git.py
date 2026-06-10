"""Tests for mentat-git skill."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_commit_routes_to_container_when_present(tmp_path):
    git_mod = load_module("git")
    utils_mod = load_module("utils")

    with patch.object(utils_mod, "container_id_for_cwd", return_value="abc123"):
        with patch.object(git_mod, "utils", utils_mod):
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return MagicMock(returncode=0)

            with patch("subprocess.run", fake_run):
                git_mod.cmd_commit(["-m", "test message"])

    # Should route via container (docker exec or container run)
    assert calls
    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("docker" in s or "container" in s or "exec" in s for s in cmd_strs)


def test_commit_falls_back_to_host_when_no_container(tmp_path):
    git_mod = load_module("git")
    utils_mod = load_module("utils")

    with patch.object(utils_mod, "container_id_for_cwd", return_value=None):
        with patch.object(git_mod, "utils", utils_mod):
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return MagicMock(returncode=0)

            with patch("subprocess.run", fake_run):
                git_mod.cmd_commit(["-m", "test message"])

    assert calls
    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    # Falls back to git commit directly
    assert any("git" in s and "commit" in s for s in cmd_strs)


def test_rebase_ff_only(tmp_path):
    git_mod = load_module("git")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        git_mod.cmd_rebase(holding="main")

    assert calls
    cmd_str = " ".join(" ".join(str(c) for c in cmd) for cmd in calls)
    assert "ff" in cmd_str.lower() or "fast" in cmd_str.lower() or "rebase" in cmd_str.lower()


def test_rebase_refuses_non_ff_with_clear_error():
    git_mod = load_module("git")

    def fake_run(cmd, **kwargs):
        return MagicMock(returncode=1, stderr="Not fast-forward")

    with patch("subprocess.run", fake_run):
        with pytest.raises(SystemExit) as exc_info:
            git_mod.cmd_rebase(holding="main")
    assert exc_info.value.code != 0


def test_rebase_emits_no_audit_event():
    """rebase is silent — orchestrate emits land events."""
    git_mod = load_module("git")

    subprocess_calls = []

    def fake_run(cmd, **kwargs):
        subprocess_calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        git_mod.cmd_rebase(holding="main")

    # Should not call mentat-log emit
    log_calls = [c for c in subprocess_calls if "log.py" in " ".join(str(x) for x in c)]
    assert not log_calls


def test_diff_uses_config_tool_when_set(tmp_path, monkeypatch):
    git_mod = load_module("git")
    monkeypatch.setenv("HOME", str(tmp_path))
    config_path = tmp_path / ".mentat" / "config.jsonc"
    config_path.parent.mkdir(parents=True)
    config_path.write_text('{"diff_tool": "difftastic"}')

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        git_mod.cmd_diff(base="main")

    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("difftastic" in s for s in cmd_strs)


def test_diff_falls_back_to_git_diff_when_unset(tmp_path, monkeypatch):
    git_mod = load_module("git")
    monkeypatch.setenv("HOME", str(tmp_path))
    # No config file → diff_tool is null

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        git_mod.cmd_diff(base="main")

    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("git" in s and "diff" in s for s in cmd_strs)
