"""Topo-sort + kind-partition + dep-aware land scheduling for mentat-orchestrate.

Owns three pieces of plan-graph logic:

  - `Plan` NamedTuple: the loaded plan tuple (slug, kind, blocked_by, path).
  - `partition(plans)`: split plans into (anchored, auto) groups.
  - `_has_upstream_hitl` / `_has_downstream_hitl`: directional walks over the
    blocked_by graph used by the partition rule.

Partition rule (topological order):

    HITL                       → anchored
    AFK with downstream HITL   → anchored
    AFK with upstream HITL     → anchored
    AFK otherwise              → auto
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.events import bind  # noqa: E402

_emit = bind("mentat-orchestrate")


class Plan(NamedTuple):
    slug: str
    kind: str
    blocked_by: list[str]
    path: Path
    touches: tuple[str, ...] = ()


def _norm_touch(path: str) -> str:
    """Normalize a declared touch-path for overlap comparison.

    Strips surrounding whitespace and a trailing slash so ``src/api/`` and
    ``src/api`` compare equal. Paths are treated as ``/``-separated regardless
    of host separator — plan write-sets are declared repo-relative POSIX.
    """
    return path.strip().rstrip("/")


def _paths_overlap(a: str, b: str) -> bool:
    """True if two touch-paths write the same file or nested tree.

    Overlap is: equality, or one path being a directory ancestor of the other
    (``src/api`` ⊃ ``src/api/routes.py``). Prefix checks respect component
    boundaries so ``src/api`` does not match ``src/api_v2.py``.
    """
    a, b = _norm_touch(a), _norm_touch(b)
    if a == b:
        return True
    lo, hi = sorted((a, b), key=len)
    return hi.startswith(lo + "/")


def _plans_conflict(p: Plan, q: Plan) -> bool:
    """True if any declared touch-path of `p` overlaps one of `q`."""
    return any(_paths_overlap(pt, qt) for pt in p.touches for qt in q.touches)


def write_conflicts(plans: list[Plan]) -> list[tuple[str, str]]:
    """Report plan pairs whose declared write-sets overlap.

    Returns ``(earlier_slug, later_slug)`` tuples in declaration order — the
    detector half of the marge-bot check. An empty result means every plan's
    write-set is disjoint and the batch can fan out fully in parallel.
    """
    conflicts: list[tuple[str, str]] = []
    for i, p in enumerate(plans):
        for q in plans[i + 1 :]:
            if _plans_conflict(p, q):
                conflicts.append((p.slug, q.slug))
    return conflicts


def serialize_conflicts(plans: list[Plan]) -> list[Plan]:
    """Return `plans` with implied `blocked_by` edges that serialize write conflicts.

    Shared serializer consumed by both the land queue's Scheduler and the
    engine's spawn-gating: for each plan, the nearest earlier plan sharing a
    touch-path is added to its `blocked_by`. This chains a whole conflict set in
    declaration order (a ← b ← c) so at most one conflicting chunk is ever in
    flight — the parallel rebase collision (the routes.py failure) cannot occur.

    Plans with disjoint write-sets are returned unchanged. Existing dependencies
    are preserved and never duplicated.
    """
    result: list[Plan] = []
    for i, p in enumerate(plans):
        prior = next(
            (plans[j].slug for j in range(i - 1, -1, -1) if _plans_conflict(p, plans[j])),
            None,
        )
        if prior is None or prior in p.blocked_by:
            result.append(p)
        else:
            result.append(p._replace(blocked_by=[*p.blocked_by, prior]))
    return result


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
                if plan.kind == "HITL":
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
            if dep_plan.kind == "HITL":
                return True
            if _walk(dep_plan.slug):
                return True
        return False

    return _walk(slug)


class Scheduler:
    """Tracks landing state of a plan set; yields ready slices whose deps are met.

    `list_ready_slices(candidates)` walks the candidate slugs in order and returns
    every slug whose `blocked_by` is wholly satisfied (every upstream is in
    `landed`). An unknown slug — chunk has no loaded plan — is treated as
    immediately ready, so ad-hoc/external chunks keep flowing without
    blocking on missing plans.

    `mark_landed` / `mark_ejected` are the only state mutations. They are
    additive: once a slug enters either set, it stays put. Ejection cascade
    walks the reverse-dep graph and pushes only *anchored* downstream slugs
    into `ejected` (NNFI); auto downstream stay pending and, because an ejected
    dep counts as resolved in `list_ready_slices`, are re-evaluated against the new
    holding tip rather than blind-ejected.
    """

    def __init__(self, plans: list[Plan]) -> None:
        self._plans: dict[str, Plan] = {p.slug: p for p in plans}
        self._landed: set[str] = set()
        self._ejected: set[str] = set()
        self._emitted_scheduled: set[str] = set()
        self._emitted_blocked: set[str] = set()
        self._emitted_skipped: set[str] = set()

    def list_ready_slices(self, candidates: list[str]) -> list[str]:
        ready: list[str] = []
        for slug in candidates:
            if slug in self._landed:
                if slug not in self._emitted_skipped:
                    _emit("slice_skipped", {"slug": slug, "reason": "landed"})
                    self._emitted_skipped.add(slug)
                continue
            if slug in self._ejected:
                if slug not in self._emitted_skipped:
                    _emit("slice_skipped", {"slug": slug, "reason": "ejected"})
                    self._emitted_skipped.add(slug)
                continue
            plan = self._plans.get(slug)
            if plan is None:
                if slug not in self._emitted_scheduled:
                    _emit("slice_scheduled", {"slug": slug})
                    self._emitted_scheduled.add(slug)
                ready.append(slug)
                continue
            deps = set(plan.blocked_by) & self._plans.keys()
            # NNFI (Zuul): an *ejected* upstream is treated as resolved, not
            # blocking. A declared-downstream auto chunk is re-evaluated against
            # the new holding tip rather than blind-cascaded — it lands if it
            # builds without the ejected change, and only ejects on its own
            # merit if it genuinely can't (rebase_conflicted / gate_failed).
            pending_deps = sorted(deps - self._landed - self._ejected)
            if pending_deps:
                if slug not in self._emitted_blocked:
                    _emit("slice_blocked", {"slug": slug, "blocked_by": pending_deps})
                    self._emitted_blocked.add(slug)
                continue
            if slug not in self._emitted_scheduled:
                _emit("slice_scheduled", {"slug": slug})
                self._emitted_scheduled.add(slug)
            ready.append(slug)
        return ready

    def mark_landed(self, slug: str) -> None:
        self._landed.add(slug)

    def _is_anchored(self, slug: str) -> bool:
        """True if `slug`'s plan is anchored (runs in-agent, never re-tested
        by the land queue). Mirrors the `partition` rule so the eject cascade
        targets exactly the plans the land queue can't re-evaluate."""
        plan = self._plans.get(slug)
        if plan is None:
            return False
        return plan.kind == "HITL" or _has_downstream_hitl(slug, self._plans) or _has_upstream_hitl(slug, self._plans)

    def has_ejections(self) -> bool:
        """True if any slug has been ejected (includes cascade victims)."""
        return bool(self._ejected)

    def ejected_slugs(self) -> frozenset[str]:
        """Return all ejected slugs (direct + cascade victims)."""
        return frozenset(self._ejected)

    def mark_ejected(self, slug: str) -> list[str]:
        """Eject slug + cascade to anchored downstream. Return cascaded list.

        NNFI (Zuul): the cascade reaches only *anchored* downstream — plans the
        land queue never re-tests (HITL, or AFK anchored via a HITL relation).
        They run in-agent, so a dead upstream must block them or the operator
        would land them on a missing change. *Auto* downstream are deliberately
        left un-ejected: the land queue re-evaluates each against the new
        holding tip and lands the ones that build without the ejected change.
        """
        self._ejected.add(slug)
        cascaded: list[str] = []
        # Walk reverse-dep graph: an anchored plan that lists an ejected slug in
        # blocked_by also gets ejected; repeat until fixed-point. Auto plans are
        # skipped — they are the land queue's re-test candidates, not victims.
        changed = True
        while changed:
            changed = False
            for other_slug, other in self._plans.items():
                if other_slug in self._ejected:
                    continue
                if not self._is_anchored(other_slug):
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
            plan.kind == "HITL"
            or _has_downstream_hitl(plan.slug, plans_by_slug)
            or _has_upstream_hitl(plan.slug, plans_by_slug)
        ):
            anchored.append(plan)
        else:
            auto.append(plan)

    return anchored, auto
