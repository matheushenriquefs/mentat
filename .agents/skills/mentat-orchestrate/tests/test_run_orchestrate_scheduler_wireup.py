"""Regression: `run_orchestrate` must hand `_land_all` plan-slug-keyed chunks.

The bug surfaced by mentat-bug-reviewer post-slice-4: `_fan_out_plans`
returns synthetic session_ids (`auto-<stem>-<pid>`), but `Scheduler` is
keyed by `plan.slug` from frontmatter. If `_land_all` is invoked with
session_ids, `Scheduler._plans.get(session_id)` returns None, the
unknown-slug fallback in `next_ready` fires for every chunk, and the
slice-2 dep gating + slice-3 eject cascade silently no-op on the prod
`run` path.

This test stubs the spawn + drain at module boundary and asserts the
chunk slugs reaching `land_queue.drain` match the plans' frontmatter
slugs — so the Scheduler can actually resolve them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_run_orchestrate_passes_plan_slugs_to_land_queue(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"
    a_path.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")
    b_path.write_text("---\nid: b\nstatus: ready\nclass: AFK\nblocked_by: [a]\n---\n# b\n")

    # Stub fan_out to return synthetic session_ids — proves the land queue
    # does NOT consume them.
    def fake_fan_out_plans(plans, *, harness=None, model=None):
        return [f"auto-{p.slug}-9999" for p in plans]

    captured: dict[str, object] = {}

    def fake_drain(chunks, *, holding, scheduler=None):
        captured["chunks"] = list(chunks)
        captured["scheduler"] = scheduler
        return [{"slug": c.slug, "status": "success", "tip": "abc"} for c in chunks]

    monkeypatch.setattr(orchestrate, "_fan_out_plans", fake_fan_out_plans)
    monkeypatch.setattr(orchestrate._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

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

    sched = captured["scheduler"]
    # Duck-type: scheduler loaded under `mentat-orchestrate.scheduler` key by
    # `_load_sibling` is a different module identity than this test's
    # `_load("scheduler")`. Match by API shape instead.
    assert sched is not None, "scheduler must be passed for dep-aware drain (slice-2)"
    assert hasattr(sched, "next_ready")
    assert hasattr(sched, "mark_landed")
    assert hasattr(sched, "mark_ejected")
    # Scheduler's plan map must include every chunk slug — otherwise
    # `next_ready` falls back to the unknown-slug branch and dep gating no-ops.
    assert set(chunk_slugs) <= set(sched._plans.keys()), (
        f"Scheduler plans {sched._plans.keys()} must cover chunk slugs {chunk_slugs}"
    )


def test_run_orchestrate_independent_afks_keep_plan_slug_identity(tmp_path, monkeypatch):
    """Two independent AFKs — chunks still arrive with plan slugs, not session_ids."""
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    a_path = tmp_path / "a.md"
    b_path = tmp_path / "b.md"
    a_path.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")
    b_path.write_text("---\nid: b\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# b\n")

    monkeypatch.setattr(
        orchestrate,
        "_fan_out_plans",
        lambda plans, **kw: [f"auto-{p.slug}-1" for p in plans],
    )

    captured_slugs: list[str] = []

    def fake_drain(chunks, *, holding, scheduler=None):
        captured_slugs.extend(c.slug for c in chunks)
        return [{"slug": c.slug, "status": "success"} for c in chunks]

    monkeypatch.setattr(orchestrate._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    orchestrate.run_orchestrate("holding", [a_path, b_path], harness=None, model=None, dry_run=False)

    assert captured_slugs == ["a", "b"], f"independent AFKs must reach land queue by plan slug; got {captured_slugs}"
