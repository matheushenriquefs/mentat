"""S1: NNFI re-test-behind after an eject — not a blind cascade (Zuul).

When chunk A ejects, its declared-downstream chunks are NOT preemptively
ejected. The land queue re-evaluates each against the new holding tip:

  - a downstream that builds *without* the ejected change still lands
    (the NNFI win — declared dep ≠ hard dep);
  - a downstream that genuinely can't build ejects on its own merit
    (rebase-conflicted / gate-failed) as the re-test surfaces it.

The blind cascade survives only for *anchored* downstream — plans the land
queue never re-tests (HITL, or AFK anchored via a HITL relation). They run
in-session, so a dead upstream must still block them.

ADR-0007: no new event names — chunk.ejected / chunk.landed / chunk.teardown.
"""

from __future__ import annotations

from pathlib import Path

import land_queue
import scheduler


def _plan(slug: str, blocked_by: list[str] | None = None, class_: str = "AFK") -> scheduler.Plan:
    return scheduler.Plan(
        slug=slug,
        class_=class_,
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
    )


def _chunk(slug: str, tmp_path: Path) -> land_queue.Chunk:
    wt = tmp_path / slug
    wt.mkdir(exist_ok=True)
    return land_queue.Chunk(slug=slug, worktree=wt)


def _install_stubs(
    monkeypatch,
    ff_calls: list[str],
    rebase_calls: list[str],
    gate_calls: list[str],
    gate_block: set[str] | None = None,
    rebase_conflict: set[str] | None = None,
    emitted: list[tuple[str, dict]] | None = None,
) -> None:
    def fake_rebase(chunk, holding):
        rebase_calls.append(chunk.slug)
        if rebase_conflict and chunk.slug in rebase_conflict:
            return (None, f"merge conflict in {chunk.slug}")
        return (f"sha-{chunk.slug}", None)

    def fake_gates(chunk):
        gate_calls.append(chunk.slug)
        if gate_block and chunk.slug in gate_block:
            return ("block", "stub-block")
        return ("pass", "")

    def fake_ff(chunk, holding):
        ff_calls.append(chunk.slug)
        return None

    def fake_emit(event, payload):
        if emitted is not None:
            emitted.append((event, payload))

    monkeypatch.setattr(land_queue, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(land_queue, "_run_gates", fake_gates)
    monkeypatch.setattr(land_queue, "_ff_merge", fake_ff)
    monkeypatch.setattr(land_queue, "_emit_event", fake_emit)
    monkeypatch.setattr(land_queue, "_teardown_container", lambda slug: None)


def _drain(chunks, sched, holding="holding"):
    return land_queue.drain(
        chunks,
        holding=holding,
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )


# ── NNFI: soft downstream is re-tested and lands ──────────────────────────────


def test_soft_downstream_retested_and_lands(tmp_path, monkeypatch) -> None:
    """A ejects; B(blocked_by=A) and C(blocked_by=B) build without A → both land."""
    a, b, c = _plan("a"), _plan("b", blocked_by=["a"]), _plan("c", blocked_by=["b"])
    sched = scheduler.Scheduler([a, b, c])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path), _chunk("c", tmp_path)]
    ff_calls: list[str] = []
    rebase_calls: list[str] = []
    gate_calls: list[str] = []
    emitted: list[tuple[str, dict]] = []
    _install_stubs(monkeypatch, ff_calls, rebase_calls, gate_calls, gate_block={"a"}, emitted=emitted)

    results = _drain(chunks, sched)

    # A blind cascade would never rebase/land b or c. NNFI re-tests them.
    assert ff_calls == ["b", "c"], f"b and c must land after re-test; ff_calls={ff_calls}"
    assert rebase_calls == ["a", "b", "c"], f"all three re-evaluated; rebase_calls={rebase_calls}"

    statuses = {r.get("slug"): r.get("status") for r in results if r.get("slug")}
    assert statuses == {"a": "eject", "b": "success", "c": "success"}

    ejections = [p for e, p in emitted if e == "chunk.ejected"]
    assert [p["slug"] for p in ejections] == ["a"], f"only a ejects; got {ejections}"
    assert ejections[0]["reason"] == "gate-failed"


def test_hard_downstream_cannot_build_ejects_on_merit(tmp_path, monkeypatch) -> None:
    """A ejects; B genuinely can't build (gate fails) → B ejects on its own merit.

    C(blocked_by=B) is then re-tested too and also can't build → ejects.
    """
    a, b, c = _plan("a"), _plan("b", blocked_by=["a"]), _plan("c", blocked_by=["b"])
    sched = scheduler.Scheduler([a, b, c])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path), _chunk("c", tmp_path)]
    ff_calls: list[str] = []
    rebase_calls: list[str] = []
    gate_calls: list[str] = []
    emitted: list[tuple[str, dict]] = []
    _install_stubs(monkeypatch, ff_calls, rebase_calls, gate_calls, gate_block={"a", "b", "c"}, emitted=emitted)

    results = _drain(chunks, sched)

    assert ff_calls == [], f"nothing lands; ff_calls={ff_calls}"
    statuses = {r.get("slug"): r.get("status") for r in results if r.get("slug")}
    assert statuses == {"a": "eject", "b": "eject", "c": "eject"}

    # Honest reasons from the re-test surface the real failure, not a synthetic tag.
    reasons = {p["slug"]: p["reason"] for e, p in emitted if e == "chunk.ejected"}
    assert reasons == {"a": "gate-failed", "b": "gate-failed", "c": "gate-failed"}


def test_hard_downstream_rebase_conflict_ejects(tmp_path, monkeypatch) -> None:
    """B's commits stacked on A won't rebase onto A-less holding → rebase-conflicted."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    ff_calls: list[str] = []
    rebase_calls: list[str] = []
    gate_calls: list[str] = []
    emitted: list[tuple[str, dict]] = []
    _install_stubs(
        monkeypatch,
        ff_calls,
        rebase_calls,
        gate_calls,
        gate_block={"a"},
        rebase_conflict={"b"},
        emitted=emitted,
    )

    _drain(chunks, sched)

    assert "b" in rebase_calls, "b must be re-tested (rebased), not blind-ejected"
    assert ff_calls == [], "b's conflicted rebase blocks the land"
    reasons = {p["slug"]: p["reason"] for e, p in emitted if e == "chunk.ejected"}
    assert reasons == {"a": "gate-failed", "b": "rebase-conflicted"}


def test_sibling_eject_does_not_cascade(tmp_path, monkeypatch) -> None:
    """Independent sibling (no dep on the ejected chunk) still lands."""
    a, b = _plan("a"), _plan("b")
    sched = scheduler.Scheduler([a, b])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    ff_calls: list[str] = []
    rebase_calls: list[str] = []
    gate_calls: list[str] = []
    emitted: list[tuple[str, dict]] = []
    _install_stubs(monkeypatch, ff_calls, rebase_calls, gate_calls, gate_block={"a"}, emitted=emitted)

    _drain(chunks, sched)

    assert "b" in ff_calls, "sibling b must land"
    b_eject = [p for e, p in emitted if e == "chunk.ejected" and p.get("slug") == "b"]
    assert b_eject == [], f"sibling b must not be ejected; got {b_eject}"


def test_event_envelope_unchanged(tmp_path, monkeypatch) -> None:
    """ADR-0007 guard: only catalog event names appear (no synthetic cascade event)."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    emitted: list[tuple[str, dict]] = []
    _install_stubs(monkeypatch, [], [], [], gate_block={"a"}, emitted=emitted)

    _drain(chunks, sched)

    event_names = {e for e, _ in emitted}
    assert event_names <= {"chunk.ejected", "chunk.landed", "chunk.teardown"}, f"unexpected events; got {event_names}"


# ── scheduler-level: cascade targets anchored downstream, spares auto ─────────


def test_cascade_targets_anchored_not_auto() -> None:
    """mark_ejected cascades to HITL/anchored downstream, never to auto downstream."""
    a = _plan("a", class_="AFK")
    b = _plan("b", blocked_by=["a"], class_="HITL")  # anchored downstream
    c = _plan("c", blocked_by=["a"], class_="AFK")  # auto downstream — re-test candidate
    sched = scheduler.Scheduler([a, b, c])

    cascaded = sched.mark_ejected("a")

    assert "b" in cascaded, "anchored HITL downstream must cascade"
    assert "c" not in cascaded, "auto downstream must be left for land-queue re-test"
    assert "b" in sched.ejected_slugs()
    assert "c" not in sched.ejected_slugs()


def test_ejected_dep_unblocks_auto_downstream() -> None:
    """next_ready treats an ejected dep as resolved so the auto downstream re-tests."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    assert sched.list_ready_slices(["b"]) == [], "b gated while a is neither landed nor ejected"
    sched.mark_ejected("a")
    assert sched.list_ready_slices(["b"]) == ["b"], "ejected a must unblock b for re-test"
