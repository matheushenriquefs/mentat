"""slice-1: scheduler.partition must promote AFK plans with upstream HITL deps.

Plan G1 — AFK.blocked_by includes a HITL plan. Existing routing.partition only
sees the *downstream* direction; the upstream-HITL AFK stays auto and would
spawn against the pre-batch base. scheduler.partition adds an `_has_upstream_hitl`
walk so those plans anchor with the HITL caller instead.

Independent AFKs (no deps) remain auto — regression guard for the no-deps path
that just landed in commits e0addbb…faf9adf.
"""

from __future__ import annotations

from pathlib import Path

import scheduler


def _plan(slug: str, kind: str, blocked_by: list[str] | None = None) -> scheduler.Plan:
    return scheduler.Plan(
        slug=slug,
        kind=kind,
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
    )


def test_afk_with_hitl_upstream_promoted_to_anchored() -> None:
    h = _plan("h", "HITL")
    a = _plan("a", "AFK", blocked_by=["h"])

    anchored, auto = scheduler.partition([h, a])

    anchored_slugs = {p.slug for p in anchored}
    auto_slugs = {p.slug for p in auto}
    assert anchored_slugs == {"h", "a"}, f"expected both anchored, got anchored={anchored_slugs} auto={auto_slugs}"
    assert auto_slugs == set()


def test_afk_with_hitl_transitive_upstream_promoted() -> None:
    h = _plan("h", "HITL")
    m = _plan("m", "AFK", blocked_by=["h"])
    a = _plan("a", "AFK", blocked_by=["m"])

    anchored, auto = scheduler.partition([h, m, a])

    assert {p.slug for p in anchored} == {"h", "m", "a"}
    assert auto == []


def test_independent_afks_remain_auto() -> None:
    a1 = _plan("a1", "AFK")
    a2 = _plan("a2", "AFK")

    anchored, auto = scheduler.partition([a1, a2])

    assert anchored == []
    assert {p.slug for p in auto} == {"a1", "a2"}


def test_afk_with_downstream_hitl_still_promoted() -> None:
    a = _plan("a", "AFK")
    h = _plan("h", "HITL", blocked_by=["a"])

    anchored, auto = scheduler.partition([a, h])

    assert {p.slug for p in anchored} == {"a", "h"}
    assert auto == []


def test_afk_chain_no_hitl_stays_auto() -> None:
    a = _plan("a", "AFK")
    b = _plan("b", "AFK", blocked_by=["a"])

    anchored, auto = scheduler.partition([a, b])

    assert anchored == []
    assert {p.slug for p in auto} == {"a", "b"}


def test_topo_order_preserved_within_partition() -> None:
    a = _plan("a", "AFK")
    b = _plan("b", "AFK", blocked_by=["a"])
    c = _plan("c", "AFK", blocked_by=["b"])

    anchored, auto = scheduler.partition([c, b, a])

    assert anchored == []
    auto_order = [p.slug for p in auto]
    assert auto_order.index("a") < auto_order.index("b") < auto_order.index("c")


def test_cycle_raises() -> None:
    a = _plan("a", "AFK", blocked_by=["b"])
    b = _plan("b", "AFK", blocked_by=["a"])

    try:
        scheduler.partition([a, b])
    except ValueError as e:
        assert "cycle" in str(e).lower()
    else:
        raise AssertionError("partition did not raise on cycle")


def test_topo_sort_tolerates_external_dep_not_in_batch() -> None:
    """A blocked_by slug absent from the batch is skipped in the topo walk."""
    a = _plan("a", "AFK", blocked_by=["already-landed-elsewhere"])

    anchored, auto = scheduler.partition([a])

    # No HITL relation and the missing dep never gates → a stays auto.
    assert anchored == []
    assert [p.slug for p in auto] == ["a"]


def test_transitive_downstream_hitl_promotes_root() -> None:
    """AFK root whose transitive downstream is HITL anchors (exercises the recursive walk)."""
    a = _plan("a", "AFK")
    b = _plan("b", "AFK", blocked_by=["a"])
    h = _plan("h", "HITL", blocked_by=["b"])

    anchored, auto = scheduler.partition([a, b, h])

    assert {p.slug for p in anchored} == {"a", "b", "h"}
    assert auto == []


def test_downstream_diamond_revisits_shared_node() -> None:
    """A diamond reverse-dep graph revisits a shared downstream node (visited guard)."""
    a = _plan("a", "AFK")
    b = _plan("b", "AFK", blocked_by=["a"])
    c = _plan("c", "AFK", blocked_by=["a"])
    d = _plan("d", "AFK", blocked_by=["b", "c"])

    anchored, auto = scheduler.partition([a, b, c, d])

    # No HITL anywhere → everything auto; the walk must still terminate.
    assert anchored == []
    assert {p.slug for p in auto} == {"a", "b", "c", "d"}


def test_upstream_diamond_revisits_shared_node() -> None:
    """A diamond forward-dep graph revisits a shared upstream node (visited guard)."""
    d = _plan("d", "AFK")
    b = _plan("b", "AFK", blocked_by=["d"])
    c = _plan("c", "AFK", blocked_by=["d"])
    a = _plan("a", "AFK", blocked_by=["b", "c"])

    anchored, auto = scheduler.partition([a, b, c, d])

    assert anchored == []
    assert {p.slug for p in auto} == {"a", "b", "c", "d"}


def test_upstream_hitl_walk_returns_false_for_unknown_slug() -> None:
    """_has_upstream_hitl on a slug absent from the map short-circuits to False."""
    assert scheduler._has_upstream_hitl("ghost", {}) is False


def test_upstream_hitl_skips_external_dep() -> None:
    """An external (out-of-batch) upstream dep is skipped, not treated as HITL."""
    a = _plan("a", "AFK", blocked_by=["external"])

    anchored, auto = scheduler.partition([a])

    assert anchored == []
    assert [p.slug for p in auto] == ["a"]
