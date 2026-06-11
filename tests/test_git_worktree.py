"""FOLLOW-UP #23 — mentat-git worktree create subcommand."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def _load_worktree():
    spec = importlib.util.spec_from_file_location("wt_mod", _SCRIPTS / "worktree.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=path, check=True, capture_output=True)
    (path / "README").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "main"
    r.mkdir()
    _init_repo(r)
    monkeypatch.chdir(r)
    return r


def test_creates_sibling_worktree(repo):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-x")
    assert rc == 0
    target = repo.parent / "feat-x"
    assert target.is_dir()
    branches = subprocess.run(["git", "branch"], cwd=repo, capture_output=True, text=True).stdout
    assert "feat-x" in branches


def test_idempotent_when_worktree_already_exists(repo):
    wt = _load_worktree()
    assert wt.cmd_worktree_create("feat-x") == 0
    assert wt.cmd_worktree_create("feat-x") == 0


def test_conflict_when_path_exists_unregistered(repo):
    wt = _load_worktree()
    (repo.parent / "feat-conflict").mkdir()
    rc = wt.cmd_worktree_create("feat-conflict")
    assert rc == 65


def test_missing_base_branch(repo):
    wt = _load_worktree()
    rc = wt.cmd_worktree_create("feat-y", base="nonexistent-branch")
    assert rc == 66


def test_custom_parent(repo, tmp_path):
    wt = _load_worktree()
    custom = tmp_path / "wts"
    rc = wt.cmd_worktree_create("feat-z", parent=custom)
    assert rc == 0
    assert (custom / "feat-z").is_dir()


def test_not_in_git_repo(tmp_path, monkeypatch):
    wt = _load_worktree()
    monkeypatch.chdir(tmp_path)
    rc = wt.cmd_worktree_create("feat-q")
    assert rc == 70


def test_cli_dispatch(repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "create", "feat-cli"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert (repo.parent / "feat-cli").is_dir()


def test_cli_worktree_help(repo):
    result = subprocess.run(
        ["python3", str(_SCRIPTS / "git.py"), "worktree", "create", "--help"],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    assert result.returncode == 0
    assert "slug" in result.stdout.lower()
