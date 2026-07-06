"""slice-2: land_queue.drain pulls chunks in topo order when given a scheduler.

G2 — AFK_b depends on AFK_a. Even if chunks arrive in reverse spawn order
(B then A), drain must land A before B because B.blocked_by includes A.

Independent AFKs with no deps preserve input order (no-deps regression
guard for the current behavior).

Stalled deps (cycle, missing upstream) → drain returns without invoking
FF-merge on the stuck chunks; payload lists the pending slugs.
"""

from __future__ import annotations

from pathlib import Path

import land_queue
import scheduler


def _plan(slug: str, blocked_by: list[str] | None = None) -> scheduler.Plan:
    return scheduler.Plan(
        slug=slug,
        class_="AFK",
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
    )


def _chunk(slug: str, tmp_path: Path) -> land_queue.Chunk:
    wt = tmp_path / slug
    wt.mkdir(exist_ok=True)
    return land_queue.Chunk(slug=slug, worktree=wt)


def _install_stubs(monkeypatch, ff_calls: list[str], gate_block: set[str] | None = None) -> None:
    """Stub git/gate layer. _rebase_chunk and _ff_merge record by slug."""

    def fake_rebase(chunk, holding):
        return (f"sha-{chunk.slug}", None)

    def fake_gates(chunk):
        if gate_block and chunk.slug in gate_block:
            return ("block", "stub-block")
        return ("pass", "")

    def fake_ff(chunk, holding):
        ff_calls.append(chunk.slug)
        return None

    monkeypatch.setattr(land_queue, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(land_queue, "_run_gates", fake_gates)
    monkeypatch.setattr(land_queue, "_ff_merge", fake_ff)
    monkeypatch.setattr(land_queue, "_emit_event", lambda *a, **kw: None)
    monkeypatch.setattr(land_queue, "_teardown_container", lambda slug: None)


def test_chain_lands_in_topo_order(tmp_path, monkeypatch) -> None:
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    chunk_b, chunk_a = _chunk("b", tmp_path), _chunk("a", tmp_path)
    ff_calls: list[str] = []
    _install_stubs(monkeypatch, ff_calls)

    results = land_queue.drain(
        [chunk_b, chunk_a],
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    assert ff_calls == ["a", "b"], f"expected topo order [a,b], got {ff_calls}"
    assert {r["slug"] for r in results if r.get("status") == "success"} == {"a", "b"}


def test_independent_afks_keep_input_order(tmp_path, monkeypatch) -> None:
    a1, a2 = _plan("a1"), _plan("a2")
    sched = scheduler.Scheduler([a1, a2])

    chunks = [_chunk("a1", tmp_path), _chunk("a2", tmp_path)]
    ff_calls: list[str] = []
    _install_stubs(monkeypatch, ff_calls)

    land_queue.drain(
        chunks,
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    assert ff_calls == ["a1", "a2"], f"expected input order, got {ff_calls}"


def test_drain_without_scheduler_is_unchanged(tmp_path, monkeypatch) -> None:
    """Regression guard: omitting scheduler keeps the legacy iter-in-order behavior."""
    chunks = [_chunk("x", tmp_path), _chunk("y", tmp_path)]
    ff_calls: list[str] = []
    _install_stubs(monkeypatch, ff_calls)

    land_queue.drain(chunks, holding="holding")

    assert ff_calls == ["x", "y"]


def test_stalled_dep_lists_pending(tmp_path, monkeypatch) -> None:
    """In-batch dep whose chunk never arrives → drain returns stalled with pending list.

    "a" is known to the scheduler but no chunk for it is passed to drain; "b"
    depends on "a" and can never become ready → stall.
    """
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    # Only b's chunk arrives — a's chunk is never queued.
    chunks = [_chunk("b", tmp_path)]
    ff_calls: list[str] = []
    _install_stubs(monkeypatch, ff_calls)

    results = land_queue.drain(
        chunks,
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    assert ff_calls == [], f"b should not have landed, ff_calls={ff_calls}"
    stalled = [r for r in results if r.get("status") == "stalled"]
    assert stalled, f"expected stalled verdict for b, got {results}"
    assert set(stalled[0].get("pending", [])) == {"b"}


def test_blocked_chunk_waits_until_upstream_lands(tmp_path, monkeypatch) -> None:
    """B reaches land_queue first but holds until A lands; B picks up immediately after."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    landed_seq: list[str] = []

    def fake_rebase(chunk, holding):
        return (f"sha-{chunk.slug}", None)

    def fake_gates(chunk):
        return ("pass", "")

    def fake_ff(chunk, holding):
        landed_seq.append(chunk.slug)
        return None

    monkeypatch.setattr(land_queue, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(land_queue, "_run_gates", fake_gates)
    monkeypatch.setattr(land_queue, "_ff_merge", fake_ff)
    monkeypatch.setattr(land_queue, "_emit_event", lambda *a, **kw: None)
    monkeypatch.setattr(land_queue, "_teardown_container", lambda slug: None)

    chunk_b, chunk_a = _chunk("b", tmp_path), _chunk("a", tmp_path)
    land_queue.drain(
        [chunk_b, chunk_a],
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    assert landed_seq[0] == "a", f"a must land before b; landed_seq={landed_seq}"
    assert landed_seq[1] == "b"


def test_scheduler_list_ready_slices_unit() -> None:
    """Direct unit on Scheduler.list_ready_slices — ready slugs with deps ⊂ landed."""
    a, b, c = _plan("a"), _plan("b", blocked_by=["a"]), _plan("c", blocked_by=["b"])
    sched = scheduler.Scheduler([a, b, c])

    assert sched.list_ready_slices(["b", "c", "a"]) == ["a"]
    sched.mark_landed("a")
    assert sched.list_ready_slices(["c", "b"]) == ["b"]
    sched.mark_landed("b")
    assert sched.list_ready_slices(["c"]) == ["c"]
    sched.mark_landed("c")
    assert sched.list_ready_slices([]) == []


def test_scheduler_unknown_slug_treated_as_ready() -> None:
    """Chunk slug not in loaded plans — drain still lands it (external/ad-hoc chunk)."""
    a = _plan("a")
    sched = scheduler.Scheduler([a])

    assert sched.list_ready_slices(["stranger"]) == ["stranger"]
