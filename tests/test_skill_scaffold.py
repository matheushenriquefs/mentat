"""Tests for mentat-skill scaffold submodule."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_scaffold_creates_skeleton(tmp_path):
    scaffold_mod = load_module("scaffold")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    scaffold_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)

    assert (skills_dir / "my-new-skill" / "SKILL.md").exists()
    assert (skills_dir / "my-new-skill" / "scripts" / "__init__.py").exists()
    assert (skills_dir / "my-new-skill" / "scripts" / "my-new-skill.py").exists()
    assert (evals_dir / "my-new-skill.json").exists()


def test_scaffold_idempotent(tmp_path):
    scaffold_mod = load_module("scaffold")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    scaffold_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)
    skill_md = skills_dir / "my-new-skill" / "SKILL.md"
    skill_md.write_text("# custom content")

    scaffold_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)
    assert skill_md.read_text() == "# custom content"


def test_scaffold_main_script_is_executable_python(tmp_path):
    scaffold_mod = load_module("scaffold")
    skills_dir = tmp_path / "skills"

    scaffold_mod.cmd_scaffold("test-skill", skills_root=skills_dir, evals_dir=tmp_path / "evals")

    main_script = skills_dir / "test-skill" / "scripts" / "test-skill.py"
    content = main_script.read_text()
    assert "#!/usr/bin/env python3" in content
    assert "def main" in content
