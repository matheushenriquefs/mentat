"""Tests for mentat-git commit submodule."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import TEST_CHUNK_ID, init_git_repo, load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _ok(stdout: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    return r


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


# ── commit.py: host identity partial branch (32->29) ──────────────────────────


def test_host_identity_skips_unset_key(monkeypatch):
    """When one git config key is unset, only the set key is forwarded."""
    commit = load_module("commit")
    monkeypatch.setattr(commit, "host_commit_identity", lambda **kw: {"user.name": "Alice"})
    args = commit._host_identity()

    assert args == ["-c", "user.name=Alice"]


# ── identity.py: container_id_for_cwd delegates to lib.devcontainer ────────────


def test_container_id_for_cwd_delegates_to_devcontainer(tmp_path, monkeypatch):
    """container_id_for_cwd derives the chunk slug from cwd and asks lib.devcontainer."""
    identity = load_module("identity")
    repo = tmp_path / "repo"
    init_git_repo(repo)
    wt = repo / ".mentat" / "worktrees" / TEST_CHUNK_ID / "my-slug"
    wt.mkdir(parents=True)
    monkeypatch.chdir(wt)

    from lib import devcontainer

    with patch.object(devcontainer, "container_id_for_slug", return_value="cid-xyz") as mock:
        result = identity.container_id_for_cwd()

    assert result == "cid-xyz"
    mock.assert_called_once_with(f"{TEST_CHUNK_ID}/my-slug")
