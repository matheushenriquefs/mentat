"""Regression: `run_orchestrate` must pass plan-slug-keyed chunks to `land_queue.drain`.

`_fan_out_plans` returns `(plan, returncode)` pairs keyed by `plan.slug` from
frontmatter. If slugs are swapped for session_ids, `Scheduler._plans.get(session_id)`
returns None, the unknown-slug fallback in `list_ready_slices` fires for every chunk, and
dep gating + eject cascade silently no-op on the prod `run` path.

This test stubs the spawn + drain at module boundary and asserts the chunk slugs
reaching `land_queue.drain` match the plans' frontmatter slugs — so the Scheduler
can actually resolve them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.conftest import TEST_CHUNK_ID, bind_chunk_worktrees, patch_orchestrate_worktree

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_orchestrate_passes_plan_slugs_to_land_queue(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"
    a_path.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# a\n")
    b_path.write_text("---\nid: b\nstatus: ready\nkind: AFK\nblocked_by: [a]\n---\n# b\n")

    # Stub fan_out to return (plan, 0) tuples — proves plan slugs reach land queue.
    worktrees: dict[str, Path] = {}

    def fake_fan_out_plans(plans, *, harness=None, model=None):
        worktrees.update(bind_chunk_worktrees(plans, tmp_path, chunk_id=TEST_CHUNK_ID))
        return [(p, 0, str(worktrees[p.slug]), None) for p in plans]

    captured: dict[str, object] = {}
    captured["chunks"] = []

    def fake_drain(chunks, *, holding, on_landed=None, on_ejected=None, list_ready_slices=None, **kw):
        captured["chunks"].extend(chunks)  # type: ignore[attr-defined]
        captured["on_landed"] = on_landed
        captured["on_ejected"] = on_ejected
        captured["list_ready_slices"] = list_ready_slices
        results = []
        for c in chunks:
            if on_landed is not None:
                on_landed(c.slug)
            results.append({"slug": c.slug, "status": "success", "tip": "abc"})
        return results

    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", fake_fan_out_plans)
    monkeypatch.setattr(orchestrate._batch, "_worktree_for_slug", lambda slug: worktrees[slug])
    monkeypatch.setattr(orchestrate._batch._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "ensure_agent", lambda *a, **k: "sess-1")

    with patch_orchestrate_worktree(orchestrate, tmp_path):
        rc = orchestrate.run_orchestrate(
            "holding",
            [a_path, b_path],
            harness=None,
            model=None,
            dry_run=False,
        )
    assert rc == 0

    chunks = captured["chunks"]
    assert isinstance(chunks, list)
    chunk_slugs = [c.slug for c in chunks]
    assert chunk_slugs == ["a", "b"], f"land queue must receive plan slugs, got {chunk_slugs}"
    # Negative guard: no session_id should leak through.
    assert not any(s.startswith("auto-") for s in chunk_slugs), f"session_ids leaked into land queue: {chunk_slugs}"

    # Callbacks must be callables wrapping a Scheduler with the right plans.
    assert callable(captured.get("list_ready_slices")), "list_ready_slices callback must be passed"
    assert callable(captured.get("on_landed")), "on_landed callback must be passed"
    assert callable(captured.get("on_ejected")), "on_ejected callback must be passed"


def test_run_orchestrate_independent_afks_keep_plan_slug_identity(tmp_path, monkeypatch):
    """Two independent AFKs — chunks still arrive with plan slugs, not session_ids."""
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"
    a_path.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# a\n")
    b_path.write_text("---\nid: b\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# b\n")

    worktrees: dict[str, Path] = {}

    def fake_fan_out(plans, **kw):
        worktrees.update(bind_chunk_worktrees(plans, tmp_path))
        return [(p, 0, str(worktrees[p.slug]), None) for p in plans]

    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(orchestrate._batch, "_worktree_for_slug", lambda slug: worktrees[slug])

    captured_slugs: list[str] = []

    def fake_drain(chunks, *, holding, on_landed=None, on_ejected=None, list_ready_slices=None, **kw):
        captured_slugs.extend(c.slug for c in chunks)
        return [{"slug": c.slug, "status": "success"} for c in chunks]

    monkeypatch.setattr(orchestrate._batch._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    with patch_orchestrate_worktree(orchestrate, tmp_path):
        orchestrate.run_orchestrate("holding", [a_path, b_path], harness=None, model=None, dry_run=False)

    assert captured_slugs == ["a", "b"], f"independent AFKs must reach land queue by plan slug; got {captured_slugs}"
