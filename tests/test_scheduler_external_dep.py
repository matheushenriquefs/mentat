"""LQ1: scheduler gates only on in-batch blocked_by deps."""

from __future__ import annotations

from pathlib import Path

import scheduler


def _plan(slug: str, blocked_by: list[str] | None = None) -> scheduler.Plan:
    return scheduler.Plan(slug=slug, kind="AFK", blocked_by=blocked_by or [], path=Path(f"/tmp/{slug}.md"))


def test_external_dep_not_in_batch_does_not_gate() -> None:
    """A plan blocked_by a slug absent from the batch becomes ready immediately."""
    p = _plan("a", blocked_by=["external-already-done"])
    sched = scheduler.Scheduler([p])
    assert sched.list_ready_slices(["a"]) == ["a"]


def test_in_batch_unlanded_dep_still_gates() -> None:
    """A plan blocked_by an in-batch unlanded slug must not be ready until it lands."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])
    assert sched.list_ready_slices(["a", "b"]) == ["a"]
    sched.mark_landed("a")
    assert sched.list_ready_slices(["b"]) == ["b"]


def test_mixed_external_and_in_batch_dep() -> None:
    """In-batch dep still gates even when an external dep is also listed."""
    a, b = _plan("a"), _plan("b", blocked_by=["external", "a"])
    sched = scheduler.Scheduler([a, b])
    assert sched.list_ready_slices(["a", "b"]) == ["a"]
    sched.mark_landed("a")
    assert sched.list_ready_slices(["b"]) == ["b"]


def test_list_ready_slices_skips_already_landed_candidate() -> None:
    """A landed slug still in the candidate list is skipped, not re-yielded."""
    a, b = _plan("a"), _plan("b")
    sched = scheduler.Scheduler([a, b])
    sched.mark_landed("a")
    assert sched.list_ready_slices(["a", "b"]) == ["b"]


def test_list_ready_slices_skips_ejected_candidate() -> None:
    """An ejected slug still in the candidate list is skipped."""
    a, b = _plan("a"), _plan("b")
    sched = scheduler.Scheduler([a, b])
    sched.mark_ejected("a")
    assert sched.list_ready_slices(["a", "b"]) == ["b"]


def test_has_ejections_reflects_eject_state() -> None:
    """has_ejections is False on a fresh scheduler, True once any slug ejects."""
    a, b = _plan("a"), _plan("b")
    sched = scheduler.Scheduler([a, b])
    assert sched.has_ejections() is False
    sched.mark_ejected("a")
    assert sched.has_ejections() is True


def test_is_anchored_false_for_unknown_slug() -> None:
    """A slug with no loaded plan is not anchored."""
    sched = scheduler.Scheduler([_plan("a")])
    assert sched._is_anchored("ghost") is False
