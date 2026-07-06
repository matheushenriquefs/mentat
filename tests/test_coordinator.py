"""Structural guard: landing must not import scheduler."""

from __future__ import annotations

import ast
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def test_land_queue_drain_does_not_import_scheduler():
    """landing.py must not import scheduler or reference Scheduler class."""
    src = (_SCRIPTS / "landing.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "scheduler", "landing must not import scheduler"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scheduler", "landing must not import from scheduler"
    assert "Scheduler" not in src, "landing must not reference Scheduler class"
    assert "scheduler" not in [node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)], (
        "landing.drain must not have 'scheduler' parameter"
    )
