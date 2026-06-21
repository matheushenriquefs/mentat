"""Tests for mentat-git CLI dispatcher."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
