"""slice-1: orchestrate must not subprocess-run implement.py for HITL plans.

Instead it emits chunk.spawned{harness:"hitl-in-session"} per HITL plan and
returns control to the calling session. Anchored slugs are NOT appended to
_land_all in the same orchestrate invocation.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_plan(tmp_path: Path, slug: str, class_: str) -> Path:
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nstatus: ready\nclass: {class_}\nblocked_by: []\n---\n\n# {slug}\n")
    return p


def test_hitl_plan_does_not_subprocess_implement(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    hitl = _write_plan(tmp_path, "fix-foo", "HITL")
    afk = _write_plan(tmp_path, "fix-bar", "AFK")

    calls = []
    real_run = orchestrate.subprocess.run

    def recording_run(cmd, *a, **kw):
        calls.append(list(cmd) if isinstance(cmd, (list, tuple)) else [cmd])
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(orchestrate.subprocess, "run", recording_run)
    monkeypatch.setattr(orchestrate, "_fan_out_plans", lambda plans, **kw: [(p, 0) for p in plans])
    landed: list[list[str]] = []

    def fake_drain(chunks, *, holding, **kw):
        landed.append([c.slug for c in chunks])
        return []

    monkeypatch.setattr(orchestrate._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)

    rc = orchestrate.run_orchestrate("holding", [hitl, afk], harness=None, model=None, dry_run=False)

    assert rc == 0
    flat = [arg for call in calls for arg in call]
    bad = [a for a in flat if isinstance(a, str) and "implement.py" in a]
    assert bad == [], f"orchestrate subprocess-ran implement.py: {bad}"
    assert landed, "land queue not invoked"
    assert all("fix-foo" not in batch for batch in landed), f"HITL slug fix-foo landed in same invocation: {landed}"


def test_hitl_emits_chunk_spawned_hitl_in_session(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    hitl = _write_plan(tmp_path, "fix-baz", "HITL")

    emitted: list[tuple[str, dict]] = []

    def fake_emit(cmd, *a, **kw):
        if isinstance(cmd, list) and len(cmd) >= 6 and cmd[2] == "emit":
            with contextlib.suppress(IndexError, json.JSONDecodeError):
                emitted.append((cmd[4], json.loads(cmd[5])))

        class _R:
            returncode = 0
            stderr = ""
            stdout = ""

        return _R()

    monkeypatch.setattr(orchestrate.subprocess, "run", fake_emit)
    monkeypatch.setattr(orchestrate, "_fan_out_plans", lambda plans, **kw: [])
    monkeypatch.setattr(orchestrate._land_queue, "drain", lambda chunks, **kw: [])
    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)

    orchestrate.run_orchestrate("holding", [hitl], harness=None, model=None, dry_run=False)

    spawned = [p for e, p in emitted if e == "chunk.spawned"]
    assert spawned, f"no chunk.spawned event emitted; got: {emitted}"
    assert any(p.get("harness") == "hitl-in-session" and p.get("slug") == "fix-baz" for p in spawned), (
        f"missing harness=hitl-in-session for fix-baz: {spawned}"
    )
