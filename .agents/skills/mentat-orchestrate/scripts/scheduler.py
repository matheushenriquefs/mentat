"""Topo-sort + class-partition + dep-aware land scheduling for mentat-orchestrate.

Owns three pieces of plan-graph logic:

  - `Plan` NamedTuple: the loaded plan tuple (slug, class_, blocked_by, path).
  - `partition(plans)`: split plans into (anchored, auto) groups.
  - `_has_upstream_hitl` / `_has_downstream_hitl`: directional walks over the
    blocked_by graph used by the partition rule.

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


def _has_downstream_hitl(slug: str, plans_by_slug: dict[str, Plan]) -> bool:
    """True if any plan transitively blocks on `slug` and is HITL."""
    visited: set[str] = set()

    def _walk(s: str) -> bool:
        if s in visited:
            return False
        visited.add(s)
        for plan in plans_by_slug.values():
            if s in plan.blocked_by:
                if plan.class_ == "HITL":
                    return True
                if _walk(plan.slug):
                    return True
        return False

    return _walk(slug)


def _has_upstream_hitl(slug: str, plans_by_slug: dict[str, Plan]) -> bool:
    """True if any plan `slug` transitively blocks-on is HITL."""
    visited: set[str] = set()

    def _walk(s: str) -> bool:
        if s in visited:
            return False
        visited.add(s)
        plan = plans_by_slug.get(s)
        if plan is None:
            return False
        for dep in plan.blocked_by:
            dep_plan = plans_by_slug.get(dep)
            if dep_plan is None:
                continue
            if dep_plan.class_ == "HITL":
                return True
            if _walk(dep_plan.slug):
                return True
        return False

    return _walk(slug)


class Scheduler:
    """Tracks landing state of a plan set; yields next chunk whose deps are met.

    `next_ready(candidates)` walks the candidate slugs in order and returns the
    first one whose `blocked_by` is wholly satisfied (every upstream is in
    `landed`). An unknown slug — chunk has no loaded plan — is treated as
    immediately ready, so ad-hoc/external chunks keep flowing the way they
    did before slice-2.

    `mark_landed` / `mark_ejected` are the only state mutations. They are
    additive: once a slug enters either set, it stays put. Ejection cascade
    (slice-3) walks the reverse-dep graph and pushes downstream slugs into
    `ejected` so they get skipped, not stalled.
    """

    def __init__(self, plans: list[Plan]) -> None:
        self._plans: dict[str, Plan] = {p.slug: p for p in plans}
        self._landed: set[str] = set()
        self._ejected: set[str] = set()

    def next_ready(self, candidates: list[str]) -> str | None:
        for slug in candidates:
            if slug in self._landed or slug in self._ejected:
                continue
            plan = self._plans.get(slug)
            if plan is None:
                return slug
            deps = set(plan.blocked_by)
            if deps - self._landed:
                continue
            return slug
        return None

    def mark_landed(self, slug: str) -> None:
        self._landed.add(slug)

    def mark_ejected(self, slug: str) -> list[str]:
        """Eject slug + cascade to every downstream slug. Return cascaded list (slice-3)."""
        self._ejected.add(slug)
        cascaded: list[str] = []
        # Walk reverse-dep graph: any plan that lists an ejected slug in
        # blocked_by also gets ejected; repeat until fixed-point.
        changed = True
        while changed:
            changed = False
            for other_slug, other in self._plans.items():
                if other_slug in self._ejected:
                    continue
                if any(dep in self._ejected for dep in other.blocked_by):
                    self._ejected.add(other_slug)
                    cascaded.append(other_slug)
                    changed = True
        return cascaded


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
