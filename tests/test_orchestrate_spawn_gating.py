"""S1: spawn-gating — a chunk fans out only once its deps are landed.

Landing was already dep-aware (``next_ready`` gates the land queue). S1 pushes the
same gate one stage earlier onto SPAWN: a chunk whose ``blocked_by`` upstream has
not landed must not branch a worktree from a base that lacks the upstream's change.
The run therefore fans out in *waves* — each wave is the set of auto plans whose
deps are all resolved (landed or NNFI-ejected), and the next wave only forms after
the current one lands.

Two gating sources, one mechanism (implied ``blocked_by`` edges via
``serialize_conflicts``): a declared ``blocked_by`` dep, and a shared declared
write-set (``touches``) — two plans that write the same path are serialized so they
never rebase-collide by running concurrently (the routes.py failure).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.conftest import bind_chunk_worktrees

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _wire(orchestrate, monkeypatch, tmp_path):
    """Record fan-out waves; make drain land every chunk (advances the scheduler)."""
    waves: list[list[str]] = []
    worktrees: dict[str, Path] = {}

    def fake_fan_out_plans(plans, *, harness=None, model=None):
        waves.append([p.slug for p in plans])
        worktrees.update(bind_chunk_worktrees(plans, tmp_path))
        return [(p, 0) for p in plans]

    def fake_drain(chunks, *, holding, on_landed=None, on_ejected=None, list_ready_slices=None, **kw):
        results = []
        for c in chunks:
            if on_landed is not None:
                on_landed(c.slug)
            results.append({"slug": c.slug, "status": "success", "tip": "x"})
        return results

    monkeypatch.setattr(orchestrate, "_fan_out_plans", fake_fan_out_plans)
    monkeypatch.setattr(orchestrate, "_worktree_for_slug", lambda slug: worktrees[slug])
    monkeypatch.setattr(orchestrate._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "_emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)
    monkeypatch.setattr(orchestrate, "_gc_preserved_worktrees", lambda **kw: None)
    return waves


def test_blocked_chunk_not_spawned_until_upstream_lands(tmp_path, monkeypatch):
    """B blocked_by A → A fans out alone, B only after A lands."""
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# a\n")
    b.write_text("---\nid: b\nstatus: ready\nkind: AFK\nblocked_by: [a]\n---\n# b\n")

    waves = _wire(orchestrate, monkeypatch, tmp_path)
    rc = orchestrate.run_orchestrate("holding", [a, b], harness=None, model=None, dry_run=False)

    assert rc == 0
    assert waves == [["a"], ["b"]], f"B must not spawn in A's wave; got {waves}"


def test_shared_write_set_chunks_never_spawn_concurrently(tmp_path, monkeypatch):
    """Two independent plans that declare the same touch-path are serialized."""
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\ntouches: [src/routes.py]\n---\n# a\n")
    b.write_text("---\nid: b\nstatus: ready\nkind: AFK\nblocked_by: []\ntouches: [src/routes.py]\n---\n# b\n")

    waves = _wire(orchestrate, monkeypatch, tmp_path)
    orchestrate.run_orchestrate("holding", [a, b], harness=None, model=None, dry_run=False)

    for w in waves:
        assert not ("a" in w and "b" in w), f"same-touch-path chunks ran concurrently: {waves}"
    assert sorted(s for w in waves for s in w) == ["a", "b"], f"both must eventually spawn; got {waves}"


def test_run_batch_stalls_when_dep_never_resolves(tmp_path, monkeypatch):
    """Anti-hang guard: a pending auto plan whose known dep never lands → stalled row,
    loop breaks (no infinite spin). Driven at the _run_batch seam with a dep (A) that
    is in known_slugs but not among the fanned auto plans, so it never resolves."""
    orchestrate = _load("orchestrate")
    scheduler = _load("scheduler")

    A = scheduler.Plan(slug="A", kind="HITL", blocked_by=[], path=Path("/tmp/A.md"))
    B = scheduler.Plan(slug="B", kind="AFK", blocked_by=["A"], path=Path("/tmp/B.md"))
    sched = scheduler.Scheduler([A, B])

    wt_map: dict[str, Path] = {}

    def fake_fan_out(plans, **kw):
        wt_map.update(bind_chunk_worktrees(plans, tmp_path))
        return [(p, 0) for p in plans]

    monkeypatch.setattr(orchestrate, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(orchestrate, "_worktree_for_slug", lambda slug: wt_map[slug])
    monkeypatch.setattr(orchestrate._land_queue, "drain", lambda chunks, **kw: [])

    results, hitl, transient = orchestrate._run_batch(
        [B], holding="h", harness=None, model=None, sched=sched, known_slugs={"A", "B"}
    )
    assert any(r.get("status") == "stalled" and r.get("pending") == ["B"] for r in results)


def test_independent_chunks_fan_out_in_one_wave(tmp_path, monkeypatch):
    """No deps, disjoint write-sets → both spawn together (no needless serialization)."""
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# a\n")
    b.write_text("---\nid: b\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# b\n")

    waves = _wire(orchestrate, monkeypatch, tmp_path)
    orchestrate.run_orchestrate("holding", [a, b], harness=None, model=None, dry_run=False)

    assert waves == [["a", "b"]], f"independent chunks must fan out in one wave; got {waves}"
