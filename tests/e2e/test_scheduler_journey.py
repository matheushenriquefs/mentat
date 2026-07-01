"""E2E: the orchestrate scheduler partitioning + dep-aware landing over a real plan graph.

Drives ``scheduler.partition`` and ``Scheduler`` (topo sort, HITL/AFK class rule,
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
    return mod.Plan(slug=slug, class_=cls, blocked_by=blocked_by or [], path=Path(f"/plans/{slug}.md"))


def test_partition_anchors_hitl_and_its_neighbors():
    m = _sched()
    # gate (HITL) ← build (AFK downstream of HITL) ← ship (AFK upstream? no) ...
    # graph: ui(AFK) blocks-on api(HITL); infra(AFK) standalone.
    plans = [
        _plan(m, "api", cls="HITL"),
        _plan(m, "ui", cls="AFK", blocked_by=["api"]),   # upstream HITL → anchored
        _plan(m, "infra", cls="AFK"),                     # standalone AFK → auto
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


def test_scheduler_next_ready_gates_on_landed_deps():
    m = _sched()
    sched = m.Scheduler([_plan(m, "a"), _plan(m, "b", blocked_by=["a"])])

    # b is blocked until a lands; a is ready first.
    assert sched.next_ready(["a", "b"]) == "a"
    sched.mark_landed("a")
    assert sched.next_ready(["b"]) == "b"


def test_scheduler_unknown_slug_is_immediately_ready():
    m = _sched()
    sched = m.Scheduler([_plan(m, "known")])
    assert sched.next_ready(["ad-hoc"]) == "ad-hoc", "chunks with no loaded plan never block"


def test_scheduler_cascade_ejects_transitive_dependents():
    m = _sched()
    sched = m.Scheduler([
        _plan(m, "root"),
        _plan(m, "mid", blocked_by=["root"]),
        _plan(m, "leaf", blocked_by=["mid"]),
        _plan(m, "island"),
    ])
    cascaded = sched.mark_ejected("root")
    assert set(cascaded) == {"mid", "leaf"}, "ejection cascades transitively"
    assert sched.has_ejections()
    assert sched.ejected_slugs() == frozenset({"root", "mid", "leaf"})
    # An ejected slug is never handed out as ready.
    assert sched.next_ready(["mid", "leaf", "island"]) == "island"
