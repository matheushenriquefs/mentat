"""Slice deepen-coordinator-rewire: orchestrate.py delegates to BatchCoordinator."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


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


def test_orchestrate_main_constructs_coordinator(tmp_path, monkeypatch):
    """run_orchestrate must delegate the AFK batch to BatchCoordinator."""
    orchestrate = _load("orchestrate")

    a_path = tmp_path / "a.md"
    a_path.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")

    constructed: list[dict] = []
    run_called: list[str] = []

    # Patch the coordinator module that orchestrate.py has already bound (_coordinator).
    coord_mod = orchestrate._coordinator

    class _FakeCoord:
        def __init__(self, **kw):
            constructed.append(kw)

        def run(self, plans, session_id, **kw):
            run_called.append(session_id)
            return coord_mod.BatchResult(session_id=session_id, landed=("a",), ejected=())

    monkeypatch.setattr(coord_mod, "BatchCoordinator", _FakeCoord)
    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    rc = orchestrate.run_orchestrate(
        "holding",
        [a_path],
        harness=None,
        model=None,
        dry_run=False,
    )

    assert constructed, "BatchCoordinator must be instantiated"
    assert run_called, "BatchCoordinator.run must be called"
    assert rc == 0, f"all landed → exit 0; got {rc}"


def test_orchestrate_exit_codes_unchanged(tmp_path, monkeypatch):
    """Ejection → exit 1; all landed → exit 0."""
    orchestrate = _load("orchestrate")
    coord_mod = orchestrate._coordinator

    a_path = tmp_path / "a.md"
    a_path.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")

    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda **kw: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    # Ejected path
    class _EjectCoord:
        def __init__(self, **kw):
            pass

        def run(self, plans, session_id, **kw):
            return coord_mod.BatchResult(session_id=session_id, landed=(), ejected=("a",))

    monkeypatch.setattr(coord_mod, "BatchCoordinator", _EjectCoord)
    rc_eject = orchestrate.run_orchestrate("holding", [a_path], harness=None, model=None, dry_run=False)
    assert rc_eject == 1, f"ejection → exit 1; got {rc_eject}"

    # Success path
    class _SuccessCoord:
        def __init__(self, **kw):
            pass

        def run(self, plans, session_id, **kw):
            return coord_mod.BatchResult(session_id=session_id, landed=("a",), ejected=())

    monkeypatch.setattr(coord_mod, "BatchCoordinator", _SuccessCoord)
    rc_ok = orchestrate.run_orchestrate("holding", [a_path], harness=None, model=None, dry_run=False)
    assert rc_ok == 0, f"all landed → exit 0; got {rc_ok}"
