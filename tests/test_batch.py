"""Tests for mentat-orchestrate batch module (staged fan-out/land coordinator)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import TEST_CHUNK_ID, bind_plan, load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


# ── _land_all dep-aware path (plans is not None) ─────────────────────────────


def test_land_all_no_plans_iterates_input_order(tmp_path):
    """`_land_all` without plans drains chunks in input order (no scheduler)."""
    batch = load_module("batch")
    bind_plan("a")

    with (
        patch.object(
            batch, "_worktree_for_slug", side_effect=lambda s: tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / s
        ),
        patch.object(batch._land_queue, "drain", return_value=[{"slug": "a", "status": "success"}]) as mock_drain,
    ):
        out = batch._land_all(["a"], holding="main")

    assert out == [{"slug": "a", "status": "success"}]
    # No scheduler callbacks when plans is None.
    _, kwargs = mock_drain.call_args
    assert "on_landed" not in kwargs


def test_land_all_with_plans_wires_scheduler_callbacks(tmp_path):
    """`_land_all` with plans builds a Scheduler and passes its callbacks to drain."""
    batch = load_module("batch")
    routing = load_module("scheduler")
    bind_plan("a")
    plan_obj = routing.Plan(slug="a", kind="AFK", blocked_by=[], path=tmp_path / "a.md")

    with (
        patch.object(
            batch, "_worktree_for_slug", side_effect=lambda s: tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / s
        ),
        patch.object(batch._land_queue, "drain", return_value=[]) as mock_drain,
    ):
        batch._land_all(["a"], holding="main", plans=[plan_obj])

    _, kwargs = mock_drain.call_args
    assert callable(kwargs["on_landed"])
    assert callable(kwargs["on_ejected"])
    assert callable(kwargs["list_ready_slices"])
