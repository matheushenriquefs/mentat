"""Slice-3: run_orchestrate prunes stale labeled containers at session start."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_plans(tmp_path: Path) -> list[Path]:
    p = tmp_path / "a.md"
    p.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")
    return [p]


def test_run_orchestrate_prunes_before_fanout(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    prune_called_before: list[bool] = []
    fan_out_called: list[bool] = []

    def fake_prune():
        prune_called_before.append(not fan_out_called)

    def fake_fan_out(plans, *, harness=None, model=None):
        fan_out_called.append(True)
        return [p.slug for p in plans]

    monkeypatch.setattr(orchestrate, "_prune_stale_containers", fake_prune)
    monkeypatch.setattr(orchestrate, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(
        orchestrate._land_queue,
        "drain",
        lambda chunks, **kw: [{"slug": c.slug, "status": "success"} for c in chunks],
    )
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    orchestrate.run_orchestrate(
        "holding",
        _make_plans(tmp_path),
        harness=None,
        model=None,
        dry_run=False,
    )

    assert prune_called_before, "prune must be called"
    assert all(prune_called_before), "prune must be called before fan-out"


def test_dry_run_skips_prune(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")

    prune_calls: list[int] = []

    def fake_prune():
        prune_calls.append(1)

    monkeypatch.setattr(orchestrate, "_prune_stale_containers", fake_prune)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)

    orchestrate.run_orchestrate(
        "holding",
        _make_plans(tmp_path),
        harness=None,
        model=None,
        dry_run=True,
    )

    assert prune_calls == [], "prune must not be called in dry-run mode"


def test_prune_failure_does_not_abort(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    def fake_subprocess_run(cmd, **kw):
        class _R:
            returncode = 1
            stdout = ""
        return _R()

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(
        orchestrate, "_fan_out_plans", lambda plans, **kw: [p.slug for p in plans]
    )
    monkeypatch.setattr(
        orchestrate._land_queue,
        "drain",
        lambda chunks, **kw: [{"slug": c.slug, "status": "success"} for c in chunks],
    )
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    rc = orchestrate.run_orchestrate(
        "holding",
        _make_plans(tmp_path),
        harness=None,
        model=None,
        dry_run=False,
    )

    assert rc == 0, "orchestrate must complete even when prune subprocess fails"
