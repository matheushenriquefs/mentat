"""Tests for mentat-skill eval submodule."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-skill/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_eval_invokes_promptfoo(tmp_path):
    eval_mod = load_module("eval")
    evals_file = tmp_path / "evals" / "my-skill.json"
    evals_file.parent.mkdir(parents=True)
    evals_file.write_text('{"skill_name":"my-skill","evals":[]}')

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0)

    with patch("subprocess.run", fake_run):
        eval_mod.cmd_eval("my-skill", evals_dir=evals_file.parent)

    assert calls
    cmd_str = " ".join(str(c) for c in calls[0])
    assert "promptfoo" in cmd_str


def test_eval_gates_promptfoo_absence(tmp_path):
    eval_mod = load_module("eval")
    evals_file = tmp_path / "evals" / "my-skill.json"
    evals_file.parent.mkdir(parents=True)
    evals_file.write_text('{"skill_name":"my-skill","evals":[]}')

    with patch("shutil.which", return_value=None), pytest.raises(SystemExit) as exc_info:
        eval_mod.cmd_eval("my-skill", evals_dir=evals_file.parent)
    assert exc_info.value.code != 0


def test_run_eval_gate_returns_true_when_no_eval_file(tmp_path):
    eval_mod = load_module("eval")
    result = eval_mod.run_eval_gate("nonexistent-skill", evals_dir=tmp_path)
    assert result is True


def test_run_eval_gate_returns_true_when_promptfoo_absent(tmp_path):
    eval_mod = load_module("eval")
    evals_file = tmp_path / "my-skill.json"
    evals_file.write_text('{"evals":[]}')
    with patch("shutil.which", return_value=None):
        result = eval_mod.run_eval_gate("my-skill", evals_dir=tmp_path)
    assert result is True
