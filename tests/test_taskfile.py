"""Taskfile wiring — the coverage gate must be a first-class task."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
TASKFILE = ROOT / "Taskfile.yml"


def _tasks() -> dict:
    data = yaml.safe_load(TASKFILE.read_text())
    return data["tasks"]


def test_coverage_task_exists() -> None:
    assert "coverage" in _tasks(), "Taskfile missing a `coverage` task"


def test_coverage_task_invokes_runner() -> None:
    cmds = _tasks()["coverage"]["cmds"]
    joined = " ".join(str(c) for c in cmds)
    assert "tasks/coverage.py" in joined, "coverage task must call tasks/coverage.py"
