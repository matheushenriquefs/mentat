"""Slice deepen-coordinator-state: BatchCoordinator + callback-based drain."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    import importlib.util

    key = f"orchestrate.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_coordinator_owns_private_scheduler_state():
    """Coordinator exposes no public landed/ejected — only BatchResult from run."""
    coord_mod = _load("coordinator")
    sched_mod = _load("scheduler")

    plan_a = sched_mod.Plan(slug="a", class_="AFK", blocked_by=[], path=Path("/tmp/a.md"))
    plan_b = sched_mod.Plan(slug="b", class_="AFK", blocked_by=[], path=Path("/tmp/b.md"))

    class _FakeFanOut:
        def run(self, plans):
            return []

    class _FakeDrain:
        def drain(self, chunks, *, holding, **kw):
            return []

    class _FakeReview:
        def review(self, session_id):
            pass

    coord = coord_mod.BatchCoordinator(
        scheduler=sched_mod.Scheduler([plan_a, plan_b]),
        fan_out=_FakeFanOut(),
        land_queue=_FakeDrain(),
        batch_review=_FakeReview(),
    )
    result = coord.run([], session_id="test-session")
    assert not hasattr(coord, "landed"), "Coordinator must not expose .landed publicly"
    assert not hasattr(coord, "ejected"), "Coordinator must not expose .ejected publicly"
    assert hasattr(result, "landed"), "BatchResult must have .landed"
    assert hasattr(result, "ejected"), "BatchResult must have .ejected"
    assert hasattr(result, "session_id"), "BatchResult must have .session_id"


def test_land_queue_drain_does_not_import_scheduler():
    """land_queue.py must not import scheduler or reference Scheduler class."""
    src = (_SCRIPTS / "land_queue.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "scheduler", "land_queue must not import scheduler"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "scheduler", "land_queue must not import from scheduler"
    assert "Scheduler" not in src, "land_queue must not reference Scheduler class"
    assert "scheduler" not in [node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)], (
        "land_queue.drain must not have 'scheduler' parameter"
    )


def test_drain_uses_callbacks():
    """BatchCoordinator passes on_landed/on_ejected callables into drain."""
    coord_mod = _load("coordinator")
    sched_mod = _load("scheduler")

    received_kwargs: dict = {}

    class _FakeFanOut:
        def run(self, plans):
            from land_queue import Chunk  # type: ignore[import]

            return [Chunk(slug="x", worktree=Path("/tmp/x"))]

    class _FakeDrain:
        def drain(self, chunks, *, holding, **kw):
            received_kwargs.update(kw)
            return [{"slug": "x", "status": "success", "tip": "sha"}]

    class _FakeReview:
        def review(self, session_id):
            pass

    coord = coord_mod.BatchCoordinator(
        scheduler=sched_mod.Scheduler([]),
        fan_out=_FakeFanOut(),
        land_queue=_FakeDrain(),
        batch_review=_FakeReview(),
    )
    coord.run([], session_id="s1")

    assert callable(received_kwargs.get("on_landed")), "drain must receive on_landed callable"
    assert callable(received_kwargs.get("on_ejected")), "drain must receive on_ejected callable"
