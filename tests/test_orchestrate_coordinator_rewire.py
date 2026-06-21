"""orchestrate.py exit-code contract: ejection → 1, all landed → 0."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"

from lib.exits import EX_HITL_REQUIRED  # noqa: E402


def _load(name: str):
    import importlib.util

    key = f"orchestrate.{name}"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_orchestrate_exit_codes_unchanged(tmp_path, monkeypatch):
    """Ejection (hitl-required child) → exit 1; all landed → exit 0."""
    orchestrate = _load("orchestrate")
    sched_mod = _load("scheduler")

    a_path = tmp_path / "a.md"
    a_path.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")

    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    plan_obj = sched_mod.Plan(slug="a", class_="AFK", blocked_by=[], path=a_path)

    # Ejected path: child exits EX_HITL_REQUIRED → hitl_slugs non-empty → exit 1
    monkeypatch.setattr(
        orchestrate,
        "_fan_out_plans",
        lambda plans, **kw: [(plan_obj, EX_HITL_REQUIRED)],
    )
    monkeypatch.setattr(orchestrate._land_queue, "drain", lambda chunks, **kw: [])
    rc_eject = orchestrate.run_orchestrate("holding", [a_path], harness=None, model=None, dry_run=False)
    assert rc_eject == 1, f"hitl-required → exit 1; got {rc_eject}"

    # Success path: all chunks land cleanly → exit 0
    monkeypatch.setattr(
        orchestrate,
        "_fan_out_plans",
        lambda plans, **kw: [(plan_obj, 0)],
    )
    monkeypatch.setattr(
        orchestrate._land_queue,
        "drain",
        lambda chunks, **kw: [{"slug": c.slug, "status": "success"} for c in chunks],
    )
    rc_ok = orchestrate.run_orchestrate("holding", [a_path], harness=None, model=None, dry_run=False)
    assert rc_ok == 0, f"all landed → exit 0; got {rc_ok}"
