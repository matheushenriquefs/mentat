"""Topo-sort + partition plans into anchored vs auto-spawn."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple


class Plan(NamedTuple):
    slug: str
    class_: str
    blocked_by: list[str]
    path: Path


def _topo_sort(plans: list[Plan]) -> list[Plan]:
    slug_map = {p.slug: p for p in plans}
    visited: set[str] = set()
    visiting: set[str] = set()
    order: list[Plan] = []

    def visit(slug: str) -> None:
        if slug in visiting:
            raise ValueError(f"cycle detected involving plan '{slug}'")
        if slug in visited:
            return
        visiting.add(slug)
        plan = slug_map.get(slug)
        if plan:
            for dep in plan.blocked_by:
                visit(dep)
        visiting.discard(slug)
        visited.add(slug)
        if plan:
            order.append(plan)

    for p in plans:
        visit(p.slug)

    return order


def _has_downstream_hitl(slug: str, plans_by_slug: dict[str, Plan], _visited: set[str] | None = None) -> bool:
    """Return True if any plan (directly or transitively) blocks on `slug` and is HITL."""
    if _visited is None:
        _visited = set()
    if slug in _visited:
        return False
    _visited.add(slug)
    for plan in plans_by_slug.values():
        if slug in plan.blocked_by:
            if plan.class_ == "HITL":
                return True
            if _has_downstream_hitl(plan.slug, plans_by_slug, _visited):
                return True
    return False


def partition(plans: list[Plan]) -> tuple[list[Plan], list[Plan]]:
    """Return (anchored_here, auto_spawn) after topological sort.

    Rules (in topo order):
    - HITL plan → anchored_here.
    - AFK plan with downstream HITL dependency → anchored_here.
    - AFK plan with no downstream HITL → auto_spawn.
    """
    topo = _topo_sort(plans)
    plans_by_slug = {p.slug: p for p in plans}

    anchored: list[Plan] = []
    auto: list[Plan] = []

    for plan in topo:
        if plan.class_ == "HITL" or _has_downstream_hitl(plan.slug, plans_by_slug):
            anchored.append(plan)
        else:
            auto.append(plan)

    return anchored, auto
