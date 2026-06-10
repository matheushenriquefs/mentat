"""Tests for mentat-skill skill."""

from __future__ import annotations

import importlib.util
import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_eval_invokes_promptfoo(tmp_path):
    skill_mod = load_module("skill")
    evals_file = tmp_path / "evals" / "my-skill.json"
    evals_file.parent.mkdir(parents=True)
    evals_file.write_text('{"skill_name":"my-skill","evals":[]}')

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        skill_mod.cmd_eval("my-skill", evals_dir=evals_file.parent)

    assert calls
    cmd_str = " ".join(str(c) for c in calls[0])
    assert "promptfoo" in cmd_str


def test_eval_gates_promptfoo_absence(tmp_path):
    skill_mod = load_module("skill")
    evals_file = tmp_path / "evals" / "my-skill.json"
    evals_file.parent.mkdir(parents=True)
    evals_file.write_text('{"skill_name":"my-skill","evals":[]}')

    import shutil
    with patch("shutil.which", return_value=None):
        with pytest.raises(SystemExit) as exc_info:
            skill_mod.cmd_eval("my-skill", evals_dir=evals_file.parent)
    assert exc_info.value.code != 0


def test_scaffold_creates_skeleton(tmp_path):
    skill_mod = load_module("skill")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    skill_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)

    assert (skills_dir / "my-new-skill" / "SKILL.md").exists()
    assert (skills_dir / "my-new-skill" / "scripts" / "__init__.py").exists()
    assert (skills_dir / "my-new-skill" / "scripts" / "my-new-skill.py").exists()
    assert (evals_dir / "my-new-skill.json").exists()


def test_scaffold_idempotent(tmp_path):
    skill_mod = load_module("skill")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"

    skill_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)
    # Write custom content to SKILL.md
    skill_md = skills_dir / "my-new-skill" / "SKILL.md"
    skill_md.write_text("# custom content")

    # Run again — should not overwrite
    skill_mod.cmd_scaffold("my-new-skill", skills_root=skills_dir, evals_dir=evals_dir)
    assert skill_md.read_text() == "# custom content"


def test_shrink_proposes_and_gates(tmp_path):
    skill_mod = load_module("skill")
    skills_dir = tmp_path / "skills"
    skill_mod.cmd_scaffold("target-skill", skills_root=skills_dir, evals_dir=tmp_path / "evals")

    skill_md = skills_dir / "target-skill" / "SKILL.md"

    with patch.object(skill_mod, "_invoke_shrink_harness", return_value="# Shorter content") as mock_shrink:
        with patch.object(skill_mod, "_run_eval_gate", return_value=True) as mock_gate:
            result = skill_mod.cmd_shrink("target-skill", skills_root=skills_dir, evals_dir=tmp_path / "evals")

    mock_shrink.assert_called_once()
    mock_gate.assert_called_once()
