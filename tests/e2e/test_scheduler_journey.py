"""E2E: the orchestrate scheduler partitioning + dep-aware landing over a real plan graph.

Drives ``scheduler.partition`` and ``Scheduler`` (topo sort, HITL/AFK kind rule,
next_ready gating, cascade ejection, cycle detection) over real ``Plan`` graphs. Pure
in-process journeys — the actual sequencing logic the orchestrator's land queue leans on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCHED_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts/scheduler.py"


def _sched():
    return load_script(SCHED_PY, "e2e_sched")


def _plan(mod, slug: str, cls: str = "AFK", blocked_by: list[str] | None = None):
    return mod.Plan(slug=slug, kind=cls, blocked_by=blocked_by or [], path=Path(f"/plans/{slug}.md"))


def test_partition_anchors_hitl_and_its_neighbors():
    m = _sched()
    # gate (HITL) ← build (AFK downstream of HITL) ← ship (AFK upstream? no) ...
    # graph: ui(AFK) blocks-on api(HITL); infra(AFK) standalone.
    plans = [
        _plan(m, "api", cls="HITL"),
        _plan(m, "ui", cls="AFK", blocked_by=["api"]),  # upstream HITL → anchored
        _plan(m, "infra", cls="AFK"),  # standalone AFK → auto
    ]
    anchored, auto = m.partition(plans)
    anchored_slugs = {p.slug for p in anchored}
    auto_slugs = {p.slug for p in auto}
    assert "api" in anchored_slugs
    assert "ui" in anchored_slugs, "AFK with an upstream HITL is anchored"
    assert auto_slugs == {"infra"}


def test_partition_anchors_afk_with_downstream_hitl():
    m = _sched()
    # base(AFK) ← gate(HITL): base has a downstream HITL → anchored.
    plans = [
        _plan(m, "base", cls="AFK"),
        _plan(m, "gate", cls="HITL", blocked_by=["base"]),
    ]
    anchored, _ = m.partition(plans)
    assert {p.slug for p in anchored} == {"base", "gate"}


def test_partition_topologically_orders_deps_first():
    m = _sched()
    plans = [
        _plan(m, "c", blocked_by=["b"]),
        _plan(m, "b", blocked_by=["a"]),
        _plan(m, "a"),
    ]
    _, auto = m.partition(plans)
    assert [p.slug for p in auto] == ["a", "b", "c"], "deps land before dependents"


def test_partition_detects_cycles():
    m = _sched()
    plans = [
        _plan(m, "x", blocked_by=["y"]),
        _plan(m, "y", blocked_by=["x"]),
    ]
    with pytest.raises(ValueError, match="cycle"):
        m.partition(plans)


def test_scheduler_list_ready_slices_gates_on_landed_deps():
    m = _sched()
    sched = m.Scheduler([_plan(m, "a"), _plan(m, "b", blocked_by=["a"])])

    assert sched.list_ready_slices(["a", "b"]) == ["a"]
    sched.mark_landed("a")
    assert sched.list_ready_slices(["b"]) == ["b"]


def test_scheduler_unknown_slug_is_immediately_ready():
    m = _sched()
    sched = m.Scheduler([_plan(m, "known")])
    assert sched.list_ready_slices(["ad-hoc"]) == ["ad-hoc"]


def test_scheduler_cascade_ejects_only_anchored_dependents():
    """NNFI: the eject cascade reaches anchored downstream (never re-tested),
    while auto downstream are left pending for re-evaluation against the new tip.

    root(AFK) ← mid(HITL, anchored) ← leaf(AFK, anchored via upstream HITL);
    auto_dep(AFK) blocks-on root but has no HITL relation → auto.
    """
    m = _sched()
    sched = m.Scheduler(
        [
            _plan(m, "root"),
            _plan(m, "mid", cls="HITL", blocked_by=["root"]),
            _plan(m, "leaf", blocked_by=["mid"]),  # anchored: upstream HITL
            _plan(m, "auto_dep", blocked_by=["root"]),
            _plan(m, "island"),
        ]
    )
    cascaded = sched.mark_ejected("root")
    assert set(cascaded) == {"mid", "leaf"}, "cascade reaches anchored dependents only"
    assert sched.has_ejections()
    assert sched.ejected_slugs() == frozenset({"root", "mid", "leaf"})
    # auto_dep is NOT ejected — its ejected dep counts as resolved, so it is
    # handed out for a re-test against the new holding tip. island has no deps.
    assert sched.list_ready_slices(["mid", "leaf", "auto_dep", "island"]) == ["auto_dep", "island"]
