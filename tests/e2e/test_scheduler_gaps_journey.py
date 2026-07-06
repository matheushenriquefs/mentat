"""E2E gap-closer: the scheduler branches the main journey test leaves uncovered.

Companion to ``test_scheduler_journey.py``. Drives ``scheduler`` (topo sort with
unknown deps, the transitive up/down-stream HITL walks including their
visited-guard and deep-recursion arms, and ``Scheduler.next_ready`` gating +
empty-ready) over real ``Plan`` graphs shaped to hit the specific branches the
happy-path journey never reaches. Pure in-process.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCHED_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts/scheduler.py"


def _sched():
    return load_script(SCHED_PY, "e2e_sched_gaps")


def _plan(mod, slug: str, cls: str = "AFK", blocked_by: list[str] | None = None):
    return mod.Plan(slug=slug, class_=cls, blocked_by=blocked_by or [], path=Path(f"/plans/{slug}.md"))


# ── _topo_sort: a blocked_by pointing at an unloaded slug ─────────────────────
# scheduler.py 44->47 (visit() with plan is None skips the dep loop) and
# 49->exit (plan is None skips the order.append).


def test_partition_tolerates_dep_on_unloaded_slug():
    m = _sched()
    # "ui" blocks on "ghost", which is never loaded as a Plan. topo must still
    # order the real plans and never emit the phantom.
    plans = [
        _plan(m, "ui", blocked_by=["ghost"]),
        _plan(m, "infra"),
    ]
    anchored, auto = m.partition(plans)
    slugs = {p.slug for p in anchored} | {p.slug for p in auto}
    assert slugs == {"ui", "infra"}, slugs
    assert "ghost" not in slugs, "an unloaded dep is never materialised as a plan"


# ── _has_downstream_hitl: deep recursion + visited guard ──────────────────────
# scheduler.py 71 (recursion into a non-HITL dependent returns True) and 64
# (a diamond re-reaches an already-visited node → the visited-guard return).


def test_partition_anchors_afk_with_transitive_downstream_hitl():
    m = _sched()
    # base(AFK) ← mid(AFK) ← gate(HITL). base's only direct dependent is mid
    # (AFK, not HITL) so the walk must recurse one hop deeper to find gate → 71.
    plans = [
        _plan(m, "base", cls="AFK"),
        _plan(m, "mid", cls="AFK", blocked_by=["base"]),
        _plan(m, "gate", cls="HITL", blocked_by=["mid"]),
    ]
    anchored, auto = m.partition(plans)
    assert {p.slug for p in anchored} == {"base", "mid", "gate"}
    assert auto == [], "the whole HITL-terminated chain is anchored"


def test_partition_downstream_walk_survives_diamond_reconvergence():
    m = _sched()
    # Diamond in the reverse-dep graph: left & right both depend on base, and
    # tip depends on BOTH. Walking base's dependents reaches tip via left, then
    # again via right → tip is already visited → the 64 guard returns False.
    # No HITL anywhere ⇒ everything is auto (and the walk terminates).
    plans = [
        _plan(m, "base", cls="AFK"),
        _plan(m, "left", cls="AFK", blocked_by=["base"]),
        _plan(m, "right", cls="AFK", blocked_by=["base"]),
        _plan(m, "tip", cls="AFK", blocked_by=["left", "right"]),
    ]
    anchored, auto = m.partition(plans)
    assert anchored == [], "no HITL ⇒ nothing anchored even across a diamond"
    assert {p.slug for p in auto} == {"base", "left", "right", "tip"}


# ── _has_upstream_hitl: None-plan, missing dep, deep recursion, diamond ────────
# scheduler.py 87 (plan is None → False), 91 (dep_plan None → continue),
# 95 (recursion into a non-HITL upstream returns True), 83 (visited guard).


def test_partition_anchors_afk_with_transitive_upstream_hitl():
    m = _sched()
    # gate(HITL) ← mid(AFK) ← leaf(AFK). leaf's direct upstream is mid (AFK),
    # so the upstream walk recurses to find gate(HITL) → line 95.
    plans = [
        _plan(m, "gate", cls="HITL"),
        _plan(m, "mid", cls="AFK", blocked_by=["gate"]),
        _plan(m, "leaf", cls="AFK", blocked_by=["mid"]),
    ]
    anchored, auto = m.partition(plans)
    assert {p.slug for p in anchored} == {"gate", "mid", "leaf"}
    assert auto == []


def test_partition_upstream_walk_ignores_missing_dep_and_terminates():
    m = _sched()
    # "leaf" blocks on "phantom" (never loaded) → dep_plan None → 91 continue.
    # With no HITL upstream, leaf is auto. This also drives the upstream walk to
    # completion without a HITL hit.
    plans = [
        _plan(m, "leaf", cls="AFK", blocked_by=["phantom"]),
    ]
    anchored, auto = m.partition(plans)
    assert anchored == []
    assert {p.slug for p in auto} == {"leaf"}


def test_partition_upstream_walk_survives_diamond_reconvergence():
    m = _sched()
    # Upstream diamond: tip depends on left & right, both depend on base(HITL).
    # Walking tip's upstreams reaches base via left AND via right → the second
    # visit hits the 83 guard. base is HITL so tip is anchored.
    plans = [
        _plan(m, "base", cls="HITL"),
        _plan(m, "left", cls="AFK", blocked_by=["base"]),
        _plan(m, "right", cls="AFK", blocked_by=["base"]),
        _plan(m, "tip", cls="AFK", blocked_by=["left", "right"]),
    ]
    anchored, auto = m.partition(plans)
    assert {p.slug for p in anchored} == {"base", "left", "right", "tip"}
    assert auto == []


# ── Scheduler.next_ready: unmet-dep skip + all-blocked None ───────────────────
# scheduler.py 130 (deps unlanded → continue) and 132 (nothing ready → None).


def test_list_ready_slices_skips_candidate_with_unmet_deps():
    m = _sched()
    sched = m.Scheduler(
        [
            _plan(m, "a"),
            _plan(m, "b", blocked_by=["a"]),
        ]
    )
    assert sched.list_ready_slices(["b", "a"]) == ["a"]


def test_list_ready_slices_returns_empty_when_all_candidates_blocked():
    m = _sched()
    sched = m.Scheduler(
        [
            _plan(m, "a"),
            _plan(m, "b", blocked_by=["a"]),
        ]
    )
    assert sched.list_ready_slices(["b"]) == []


def test_list_ready_slices_returns_empty_when_every_candidate_already_settled():
    m = _sched()
    sched = m.Scheduler([_plan(m, "a"), _plan(m, "b")])
    sched.mark_landed("a")
    sched.mark_ejected("b")
    assert sched.list_ready_slices(["a", "b"]) == []
