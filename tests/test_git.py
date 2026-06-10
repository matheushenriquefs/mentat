"""Tests for mentat-git CLI dispatcher."""

from __future__ import annotations

import subprocess
from pathlib import Path

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
