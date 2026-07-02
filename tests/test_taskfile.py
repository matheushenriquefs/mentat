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


def test_coverage_task_runs_unit_fast_suite() -> None:
    """The unit gate excludes e2e-marked tests and gates the fast suite at 100%."""
    joined = " ".join(str(c) for c in _tasks()["coverage"]["cmds"])
    assert "not e2e" in joined, "unit gate must select the fast suite (-m 'not e2e')"
    assert "--fail-under=100" in joined, "unit gate must gate at 100% (its own explicit floor)"


def test_coverage_task_wires_e2e_gate() -> None:
    """The e2e gate runs the e2e journeys over .agents at the journey floor.

    The floor caps well below the unit gate: Docker-in-Docker, real-harness spawn,
    worktree plumbing and the gate toolchain are not e2e-reachable inside the
    devcontainer (see ADR-0014), so e2e only ratchets journey coverage.
    """
    joined = " ".join(str(c) for c in _tasks()["coverage"]["cmds"])
    assert "--source=.agents" in joined, "e2e gate must source .agents"
    assert "--fail-under=70" in joined, "e2e gate must gate at the journey floor (70)"
    assert "-m e2e" in joined, "e2e gate must select the e2e journeys"
