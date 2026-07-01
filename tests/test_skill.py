"""Tests for mentat-skill CLI dispatcher."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def _load(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_skill_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "skill.py"), "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "mentat-skill" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_registry_default_paths():
    reg = _load("registry")
    assert reg.default_skills_root().name == "skills"
    assert reg.default_evals_dir().name == "evals"


def test_skill_scaffold_subcommand_help():
    result = subprocess.run(
        ["python3", str(SCRIPTS / "skill.py"), "scaffold", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
