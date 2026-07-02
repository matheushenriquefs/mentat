"""S2: write-set conflict pre-detection (marge-bot).

Two plans that declare the same touch-path collide at rebase when they run in
parallel (the routes.py failure). The scheduler must pre-detect the overlap and
serialize (chain) the conflicting chunks so only one is in flight at a time.

`write_conflicts` is the detector — it flags overlapping declared write-sets.
`serialize_conflicts` is the shared serializer — it returns the plans with
implied `blocked_by` edges added, so both the land queue's Scheduler and the
engine's spawn-gating run the conflicting chunks one after another.
"""

from __future__ import annotations

from pathlib import Path

import scheduler


def _plan(
    slug: str,
    *,
    touches: tuple[str, ...] = (),
    blocked_by: list[str] | None = None,
) -> scheduler.Plan:
    return scheduler.Plan(
        slug=slug,
        class_="AFK",
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
        touches=touches,
    )


# ── Plan.touches default ──────────────────────────────────────────────────────


def test_plan_touches_defaults_empty() -> None:
    """Existing callers that omit `touches` still construct a valid Plan."""
    p = scheduler.Plan(slug="a", class_="AFK", blocked_by=[], path=Path("/tmp/a.md"))
    assert p.touches == ()


# ── write_conflicts detector ──────────────────────────────────────────────────


def test_shared_touch_path_flagged() -> None:
    a = _plan("a", touches=("src/routes.py",))
    b = _plan("b", touches=("src/routes.py",))

    conflicts = scheduler.write_conflicts([a, b])

    assert conflicts == [("a", "b")], f"expected a/b overlap flagged, got {conflicts}"


def test_disjoint_touch_paths_no_conflict() -> None:
    a = _plan("a", touches=("src/routes.py",))
    b = _plan("b", touches=("src/models.py",))

    assert scheduler.write_conflicts([a, b]) == []


def test_directory_prefix_overlap_flagged() -> None:
    """A plan touching a dir conflicts with one touching a file under that dir."""
    a = _plan("a", touches=("src/api/",))
    b = _plan("b", touches=("src/api/routes.py",))

    assert scheduler.write_conflicts([a, b]) == [("a", "b")]


def test_partial_path_component_not_a_prefix() -> None:
    """`src/api` must not match `src/api_v2.py` — component boundary respected."""
    a = _plan("a", touches=("src/api",))
    b = _plan("b", touches=("src/api_v2.py",))

    assert scheduler.write_conflicts([a, b]) == []


def test_conflicts_are_ordered_by_declaration() -> None:
    a = _plan("a", touches=("f.py",))
    b = _plan("b", touches=("f.py",))
    c = _plan("c", touches=("f.py",))

    conflicts = scheduler.write_conflicts([a, b, c])

    assert conflicts == [("a", "b"), ("a", "c"), ("b", "c")]


def test_no_touches_never_conflicts() -> None:
    a = _plan("a")
    b = _plan("b")

    assert scheduler.write_conflicts([a, b]) == []


# ── serialize_conflicts ───────────────────────────────────────────────────────


def test_serialize_chains_conflicting_pair() -> None:
    a = _plan("a", touches=("routes.py",))
    b = _plan("b", touches=("routes.py",))

    chained = {p.slug: p for p in scheduler.serialize_conflicts([a, b])}

    assert chained["a"].blocked_by == []
    assert "a" in chained["b"].blocked_by, "b must chain behind a to serialize the write-set"


def test_serialize_preserves_existing_blocked_by() -> None:
    a = _plan("a", touches=("routes.py",))
    b = _plan("b", touches=("routes.py",), blocked_by=["x"])

    chained = {p.slug: p for p in scheduler.serialize_conflicts([a, b])}

    assert "x" in chained["b"].blocked_by
    assert "a" in chained["b"].blocked_by


def test_serialize_leaves_disjoint_plans_untouched() -> None:
    a = _plan("a", touches=("routes.py",))
    b = _plan("b", touches=("models.py",))

    chained = {p.slug: p for p in scheduler.serialize_conflicts([a, b])}

    assert chained["a"].blocked_by == []
    assert chained["b"].blocked_by == []


def test_serialize_chains_whole_conflict_set_in_order() -> None:
    """a, b, c all touch the same file → chained a ← b ← c (each behind prior)."""
    a = _plan("a", touches=("f.py",))
    b = _plan("b", touches=("f.py",))
    c = _plan("c", touches=("f.py",))

    chained = {p.slug: p for p in scheduler.serialize_conflicts([a, b, c])}

    assert chained["a"].blocked_by == []
    assert chained["b"].blocked_by == ["a"]
    assert chained["c"].blocked_by == ["b"]


def test_serialize_does_not_duplicate_when_already_dependent() -> None:
    """If b already blocks on a, serialize must not add a duplicate edge."""
    a = _plan("a", touches=("f.py",))
    b = _plan("b", touches=("f.py",), blocked_by=["a"])

    chained = {p.slug: p for p in scheduler.serialize_conflicts([a, b])}

    assert chained["b"].blocked_by.count("a") == 1


def test_serialized_plans_drive_scheduler_serialization() -> None:
    """End-to-end: feeding serialized plans to the Scheduler serializes the land order."""
    a = _plan("a", touches=("routes.py",))
    b = _plan("b", touches=("routes.py",))

    sched = scheduler.Scheduler(scheduler.serialize_conflicts([a, b]))

    # b is chained behind a → only a is ready first.
    assert sched.next_ready(["a", "b"]) == "a"
    assert sched.next_ready(["b"]) is None, "b must wait until a lands"
    sched.mark_landed("a")
    assert sched.next_ready(["b"]) == "b"
