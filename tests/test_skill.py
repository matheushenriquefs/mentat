"""Tests for mentat-skill CLI dispatcher."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def test_skill_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "skill.py"), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "mentat-skill" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_skill_scaffold_subcommand_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "skill.py"), "scaffold", "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
