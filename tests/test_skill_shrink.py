"""Tests for mentat-skill shrink submodule."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_shrink_proposes_and_gates(tmp_path):
    shrink_mod = load_module("shrink")
    scaffold_mod = load_module("scaffold")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"
    scaffold_mod.cmd_scaffold("target-skill", skills_root=skills_dir, evals_dir=evals_dir)

    with (
        patch.object(shrink_mod, "_invoke_shrink_harness", return_value="# Shorter content") as mock_shrink,
        patch.object(shrink_mod._eval, "run_eval_gate", return_value=True) as mock_gate,
    ):
        shrink_mod.cmd_shrink("target-skill", skills_root=skills_dir, evals_dir=evals_dir)

    mock_shrink.assert_called_once()
    mock_gate.assert_called_once()


def test_shrink_noop_when_no_change(tmp_path):
    shrink_mod = load_module("shrink")
    scaffold_mod = load_module("scaffold")
    skills_dir = tmp_path / "skills"
    evals_dir = tmp_path / "evals"
    scaffold_mod.cmd_scaffold("target-skill", skills_root=skills_dir, evals_dir=evals_dir)
    original = (skills_dir / "target-skill" / "SKILL.md").read_text()

    with patch.object(shrink_mod, "_invoke_shrink_harness", return_value=original):
        rc = shrink_mod.cmd_shrink("target-skill", skills_root=skills_dir, evals_dir=evals_dir)

    assert rc == 0
    assert (skills_dir / "target-skill" / "SKILL.md").read_text() == original


def test_shrink_missing_skill_returns_1(tmp_path):
    shrink_mod = load_module("shrink")
    rc = shrink_mod.cmd_shrink("no-such-skill", skills_root=tmp_path / "skills", evals_dir=tmp_path)
    assert rc == 1
