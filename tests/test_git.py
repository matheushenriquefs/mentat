"""Tests for mentat-git CLI dispatcher."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-git/scripts"


def test_git_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "git.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "mentat-git" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_git_commit_subcommand_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "git.py"), "commit", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


# ── B4: diff subcommand must be removed ───────────────────────────────────────


def test_git_parser_rejects_diff_subcommand():
    """After B4, `mentat-git diff` must exit 2 (unknown subcommand)."""
    git = load_script(SCRIPTS / "git.py", "mentat_git")

    with pytest.raises(SystemExit) as exc:
        git.build_parser().parse_args(["diff", "main"])
    assert exc.value.code == 2, f"expected argparse exit 2, got {exc.value.code}"


def test_git_diff_py_file_removed():
    """After B4, diff.py must not exist in the mentat-git scripts dir."""
    diff_script = SCRIPTS / "diff.py"
    assert not diff_script.exists(), "diff.py must be removed (B4)"


def test_git_no_diff_sibling_load():
    """After B4, git.py must not load_sibling 'diff'."""
    src = (SCRIPTS / "git.py").read_text()
    # load_sibling(__file__, "diff") must be gone
    assert 'load_sibling(__file__, "diff")' not in src
    assert "load_sibling(__file__, 'diff')" not in src


# ── main() dispatch ───────────────────────────────────────────────────────────


def test_main_dispatches_commit(monkeypatch):
    git = load_script(SCRIPTS / "git.py", "mentat_git_main_commit")
    monkeypatch.setattr("sys.argv", ["git.py", "commit"])
    with patch.object(git, "cmd_commit", return_value=0) as mock:
        with pytest.raises(SystemExit) as exc:
            git.main()
    assert exc.value.code == 0
    mock.assert_called_once_with([])


def test_main_dispatches_rebase(monkeypatch):
    git = load_script(SCRIPTS / "git.py", "mentat_git_main_rebase")
    monkeypatch.setattr("sys.argv", ["git.py", "rebase", "main"])
    with patch.object(git, "cmd_rebase", return_value=0) as mock:
        with pytest.raises(SystemExit) as exc:
            git.main()
    assert exc.value.code == 0
    mock.assert_called_once_with("main")


def test_main_dispatches_worktree_create(monkeypatch):
    git = load_script(SCRIPTS / "git.py", "mentat_git_main_wt_create")
    monkeypatch.setattr("sys.argv", ["git.py", "worktree", "create", "my-slug"])
    with patch.object(git, "cmd_worktree_create", return_value=0) as mock:
        with pytest.raises(SystemExit) as exc:
            git.main()
    assert exc.value.code == 0
    mock.assert_called_once_with("my-slug", base=None, parent=None)


def test_main_dispatches_worktree_sweep(monkeypatch):
    git = load_script(SCRIPTS / "git.py", "mentat_git_main_wt_sweep")
    monkeypatch.setattr("sys.argv", ["git.py", "worktree", "sweep"])
    with patch.object(git, "cmd_worktree_sweep", return_value=0) as mock:
        with pytest.raises(SystemExit) as exc:
            git.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(dry_run=True)


def test_main_dispatches_worktree_sweep_force(monkeypatch):
    git = load_script(SCRIPTS / "git.py", "mentat_git_main_wt_sweep_force")
    monkeypatch.setattr("sys.argv", ["git.py", "worktree", "sweep", "--force"])
    with patch.object(git, "cmd_worktree_sweep", return_value=0) as mock:
        with pytest.raises(SystemExit) as exc:
            git.main()
    assert exc.value.code == 0
    mock.assert_called_once_with(dry_run=False)


# ── git.py CLI: unknown subcommand combination (67->exit) ─────────────────────


def test_git_main_worktree_unknown_combo_falls_through(monkeypatch):
    """main() with a worktree subcommand that matches no branch falls through (67->exit).

    Patch parse_args to yield a (cmd=worktree, wt_cmd=other) namespace the dispatch
    ladder does not match, so main() returns without sys.exit.
    """
    import argparse

    git = load_script(SCRIPTS / "git.py", "mentat_git_falls_through")
    ns = argparse.Namespace(cmd="worktree", wt_cmd="other")
    monkeypatch.setattr(git.argparse.ArgumentParser, "parse_args", lambda self, *a, **k: ns)

    # Must return (None) without raising SystemExit — no branch matched.
    assert git.main() is None
