"""Tests for mentat-orchestrate routing module."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def make_plan(slug: str, class_: str, blocked_by: list[str] | None = None):
    routing = load_module("scheduler")
    return routing.Plan(
        slug=slug,
        class_=class_,
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
    )


def test_routing_single_hitl_anchored():
    routing = load_module("scheduler")
    plans = [make_plan("p1", "HITL")]
    anchored, auto = routing.partition(plans)
    assert anchored == [plans[0]]
    assert auto == []


def test_routing_single_afk_auto_spawned():
    routing = load_module("scheduler")
    plans = [make_plan("p1", "AFK")]
    anchored, auto = routing.partition(plans)
    assert anchored == []
    assert auto == [plans[0]]


def test_routing_n_afk_all_spawned():
    routing = load_module("scheduler")
    plans = [make_plan(f"p{i}", "AFK") for i in range(3)]
    anchored, auto = routing.partition(plans)
    assert anchored == []
    assert len(auto) == 3


def test_routing_hitl_plus_independent_afk_partitions_correctly():
    routing = load_module("scheduler")
    hitl = make_plan("hitl", "HITL")
    afk = make_plan("afk", "AFK")
    anchored, auto = routing.partition([hitl, afk])
    assert hitl in anchored
    assert afk in auto


def test_routing_afk_blocking_hitl_anchors_afk():
    """AFK that a HITL plan depends on must anchor (same session)."""
    routing = load_module("scheduler")
    afk = make_plan("afk", "AFK")
    hitl = make_plan("hitl", "HITL", blocked_by=["afk"])
    anchored, auto = routing.partition([afk, hitl])
    # afk blocked-by dependency chain leads to hitl — afk must anchor
    assert afk in anchored
    assert hitl in anchored
    assert auto == []


def test_routing_hitl_blocking_afk_anchors_dependent_afk():
    """AFK that directly blocks a HITL (HITL blocked_by AFK) → AFK anchors."""
    routing = load_module("scheduler")
    afk = make_plan("afk", "AFK")
    hitl = make_plan("hitl", "HITL", blocked_by=["afk"])
    anchored, auto = routing.partition([hitl, afk])
    assert afk in anchored


def test_routing_cycle_raises():
    routing = load_module("scheduler")
    p1 = make_plan("p1", "AFK", blocked_by=["p2"])
    p2 = make_plan("p2", "AFK", blocked_by=["p1"])
    with pytest.raises(ValueError, match="cycle"):
        routing.partition([p1, p2])
