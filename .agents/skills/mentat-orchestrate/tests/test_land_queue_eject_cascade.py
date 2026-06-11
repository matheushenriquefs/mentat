"""slice-3: ejecting an upstream chunk cascades to downstream chunks.

G3 — when chunk A ejects (gate-failed, rebase-conflicted, not-ff), every
downstream chunk that transitively depends on A is preemptively ejected
with `chunk.ejected{reason:"upstream_ejected", upstream:<A>}` and is
never rebased / gated.

Sibling chunks (no dep on the ejected one) are unaffected — regression
guard for the independent-AFK path.

ADR-0007: the eject envelope is reused; only the payload extends with
`reason="upstream_ejected"` and `upstream:<slug>`. No new event names.
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


def _install_stubs(
    monkeypatch,
    ff_calls: list[str],
    rebase_calls: list[str],
    gate_calls: list[str],
    gate_block: set[str] | None = None,
    emitted: list[tuple[str, dict]] | None = None,
) -> None:
    def fake_rebase(chunk, holding):
        rebase_calls.append(chunk.slug)
        return (f"sha-{chunk.slug}", None)

    def fake_gates(chunk):
        gate_calls.append(chunk.slug)
        if gate_block and chunk.slug in gate_block:
            return ("block", "stub-block")
        return ("pass", "")

    def fake_ff(chunk, holding):
        ff_calls.append(chunk.slug)
        return True

    def fake_emit(event, payload):
        if emitted is not None:
            emitted.append((event, payload))

    monkeypatch.setattr(land_queue, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(land_queue, "_run_gates", fake_gates)
    monkeypatch.setattr(land_queue, "_ff_merge", fake_ff)
    monkeypatch.setattr(land_queue, "_emit_event", fake_emit)


def test_upstream_eject_cascades_downstream(tmp_path, monkeypatch) -> None:
    a, b, c = _plan("a"), _plan("b", blocked_by=["a"]), _plan("c", blocked_by=["b"])
    sched = scheduler.Scheduler([a, b, c])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path), _chunk("c", tmp_path)]
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
        emitted=emitted,
    )

    results = land_queue.drain(chunks, holding="holding", scheduler=sched)

    assert ff_calls == [], f"no chunk should land; ff_calls={ff_calls}"
    assert rebase_calls == ["a"], f"only a should rebase; rebase_calls={rebase_calls}"

    ejections = [p for e, p in emitted if e == "chunk.ejected"]
    by_slug = {p.get("slug"): p for p in ejections}
    assert by_slug.get("a", {}).get("reason") == "gate-failed"
    assert by_slug.get("b", {}).get("reason") == "upstream_ejected"
    assert by_slug.get("c", {}).get("reason") == "upstream_ejected"
    assert "upstream" in by_slug["b"], "b's eject payload must carry upstream slug"
    assert "upstream" in by_slug["c"], "c's eject payload must carry upstream slug"

    statuses = {r.get("slug"): r.get("status") for r in results if r.get("slug")}
    assert statuses == {"a": "eject", "b": "eject", "c": "eject"}


def test_sibling_eject_does_not_cascade(tmp_path, monkeypatch) -> None:
    a, b = _plan("a"), _plan("b")
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
        emitted=emitted,
    )

    land_queue.drain(chunks, holding="holding", scheduler=sched)

    assert "b" in rebase_calls, "sibling b must still attempt rebase"
    assert "b" in gate_calls, "sibling b must still run gates"
    assert "b" in ff_calls, "sibling b must still FF-merge"

    ejections = [p for e, p in emitted if e == "chunk.ejected"]
    b_eject = [p for p in ejections if p.get("slug") == "b"]
    assert b_eject == [], f"sibling b must not be cascade-ejected; got {b_eject}"


def test_rebase_conflict_cascades(tmp_path, monkeypatch) -> None:
    """Rebase-conflict eject (not gate fail) also cascades downstream."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    rebase_calls: list[str] = []
    emitted: list[tuple[str, dict]] = []

    def fake_rebase(chunk, holding):
        rebase_calls.append(chunk.slug)
        if chunk.slug == "a":
            return (None, "merge conflict in foo.py")
        return (f"sha-{chunk.slug}", None)

    def fake_emit(event, payload):
        emitted.append((event, payload))

    monkeypatch.setattr(land_queue, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(land_queue, "_run_gates", lambda c: ("pass", ""))
    monkeypatch.setattr(land_queue, "_ff_merge", lambda c, h: True)
    monkeypatch.setattr(land_queue, "_emit_event", fake_emit)

    land_queue.drain(chunks, holding="holding", scheduler=sched)

    assert rebase_calls == ["a"], f"b must not rebase after a conflicts; rebase_calls={rebase_calls}"
    ejections = {p.get("slug"): p for e, p in emitted if e == "chunk.ejected"}
    assert ejections["a"]["reason"] == "rebase-conflicted"
    assert ejections["b"]["reason"] == "upstream_ejected"
    assert ejections["b"].get("upstream") == "a"


def test_eject_event_envelope_unchanged(tmp_path, monkeypatch) -> None:
    """ADR-0007 guard: only the chunk.ejected event name is used; no new event."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    emitted: list[tuple[str, dict]] = []
    _install_stubs(
        monkeypatch,
        [],
        [],
        [],
        gate_block={"a"},
        emitted=emitted,
    )

    land_queue.drain(chunks, holding="holding", scheduler=sched)

    event_names = {e for e, _ in emitted}
    assert event_names <= {"chunk.ejected"}, f"only chunk.ejected expected; got {event_names}"
