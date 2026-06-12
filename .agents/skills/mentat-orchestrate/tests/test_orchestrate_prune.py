"""Slice-3: run_orchestrate prunes stale labeled containers at session start."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_AGENTS_ROOT = Path(__file__).resolve().parents[3]  # .agents/
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))
from lib import devcontainer as _dc_mod  # noqa: E402
from lib.devcontainer import PruneResult  # noqa: E402


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


def test_prune_stale_containers_delegates_to_devcontainer(monkeypatch):
    orchestrate = _load("orchestrate")

    emit_calls: list[tuple] = []
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda ev, payload: emit_calls.append((ev, payload)))
    monkeypatch.setattr(_dc_mod, "prune", lambda: PruneResult(reclaimed_bytes=999, containers_removed=2))

    orchestrate._prune_stale_containers()

    assert emit_calls == [("session.prune", {"reclaimed_bytes": 999})]


def test_orchestrate_does_not_call_docker_directly():
    import ast

    source = (ORCH_SCRIPTS / "orchestrate.py").read_text()
    tree = ast.parse(source)

    docker_calls: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in ("run", "Popen")):
            continue
        if not node.args:
            continue
        first_arg = node.args[0]
        if not isinstance(first_arg, ast.List) or not first_arg.elts:
            continue
        first_elem = first_arg.elts[0]
        if isinstance(first_elem, ast.Constant) and first_elem.value == "docker":
            docker_calls.append(node.lineno)

    assert not docker_calls, f"docker called directly via subprocess at lines: {docker_calls}"


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
    monkeypatch.setattr(orchestrate, "_fan_out_plans", lambda plans, **kw: [p.slug for p in plans])
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
