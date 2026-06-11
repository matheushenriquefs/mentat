"""Topo-sort + class-partition + dep-aware land scheduling for mentat-orchestrate.

Owns three pieces of plan-graph logic:

  - `Plan` NamedTuple: the loaded plan tuple (slug, class_, blocked_by, path).
  - `partition(plans)`: split plans into (anchored, auto) groups.
  - `_has_upstream_hitl` / `_has_downstream_hitl`: directional walks over the
    blocked_by graph used by the partition rule.

`routing.py` is a thin re-export shim kept for backward-compat with existing
`_load_sibling("routing")` callers.

Partition rule (topological order):

    HITL                       → anchored
    AFK with downstream HITL   → anchored   (existing G2 rule)
    AFK with upstream HITL     → anchored   (G1 — added in this slice)
    AFK otherwise              → auto
"""

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


def _has_downstream_hitl(
    slug: str,
    plans_by_slug: dict[str, Plan],
    _visited: set[str] | None = None,
) -> bool:
    """True if any plan transitively blocks on `slug` and is HITL."""
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


def _has_upstream_hitl(
    slug: str,
    plans_by_slug: dict[str, Plan],
    _visited: set[str] | None = None,
) -> bool:
    """True if any plan `slug` transitively blocks-on is HITL.

    Mirror of `_has_downstream_hitl` over the reverse direction. The G1 fix:
    an AFK whose upstream is HITL must anchor with the caller — the caller
    drives the HITL in-session, so the AFK can't auto-spawn until after that
    HITL lands. Promotion to anchored holds it back; the caller re-invokes
    `orchestrate land-queue` once the upstream chunk is in.
    """
    if _visited is None:
        _visited = set()
    if slug in _visited:
        return False
    _visited.add(slug)
    plan = plans_by_slug.get(slug)
    if plan is None:
        return False
    for dep in plan.blocked_by:
        dep_plan = plans_by_slug.get(dep)
        if dep_plan is None:
            continue
        if dep_plan.class_ == "HITL":
            return True
        if _has_upstream_hitl(dep_plan.slug, plans_by_slug, _visited):
            return True
    return False


def partition(plans: list[Plan]) -> tuple[list[Plan], list[Plan]]:
    """Return (anchored, auto) after topological sort.

    See module docstring for the rule table.
    """
    topo = _topo_sort(plans)
    plans_by_slug = {p.slug: p for p in plans}

    anchored: list[Plan] = []
    auto: list[Plan] = []

    for plan in topo:
        if (
            plan.class_ == "HITL"
            or _has_downstream_hitl(plan.slug, plans_by_slug)
            or _has_upstream_hitl(plan.slug, plans_by_slug)
        ):
            anchored.append(plan)
        else:
            auto.append(plan)

    return anchored, auto
