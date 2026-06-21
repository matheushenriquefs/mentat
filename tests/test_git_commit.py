"""Tests for mentat-git commit submodule."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_commit_routes_to_container_when_present():
    commit_mod = load_module("commit")
    utils_mod = load_module("identity")

    with (
        patch.object(utils_mod, "container_id_for_cwd", return_value="abc123"),
        patch.object(commit_mod, "utils", utils_mod),
    ):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", fake_run):
            commit_mod.cmd_commit(["-m", "test message"])

    assert calls
    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("docker" in s or "container" in s or "exec" in s for s in cmd_strs)


def test_commit_auto_ups_when_no_container_then_commits():
    commit_mod = load_module("commit")
    utils_mod = load_module("identity")

    cid_sequence = iter([None, "abc123"])
    with (
        patch.object(utils_mod, "container_id_for_cwd", side_effect=lambda: next(cid_sequence)),
        patch.object(commit_mod, "utils", utils_mod),
    ):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0, stdout="/repo\n")

        with patch("subprocess.run", fake_run):
            rc = commit_mod.cmd_commit(["-m", "msg"])

    assert rc == 0
    cmd_strs = [" ".join(str(c) for c in cmd) for cmd in calls]
    assert any("container.py" in s and "up" in s for s in cmd_strs), "auto-up not invoked"
    assert any("docker" in s and "exec" in s for s in cmd_strs), "container commit path not taken"


def test_commit_exits_69_when_bringup_fails():
    commit_mod = load_module("commit")
    utils_mod = load_module("identity")

    with (
        patch.object(utils_mod, "container_id_for_cwd", return_value=None),
        patch.object(commit_mod, "utils", utils_mod),
    ):

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=0)

        with patch("subprocess.run", fake_run):
            rc = commit_mod.cmd_commit(["-m", "msg"])

    assert rc == 69
