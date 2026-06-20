"""Slice-3: run_orchestrate prunes stale labeled containers at session start.
Slice port-worktree-prune: prune stale worktrees at session-end with dirty-check.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time as _time
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


def test_prune_stale_containers_delegates_to_devcontainer(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)  # no .mentat/worktrees/ → no dirty-check interference

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


# ── shell-port-worktree-prune helpers ────────────────────────────────────────


def _cp_proc(returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess:  # type: ignore[type-arg]
    r: subprocess.CompletedProcess = subprocess.CompletedProcess.__new__(subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = ""
    r.args = []
    return r


def _make_wt(wt_root: Path, name: str, *, age_secs: int = 7200) -> Path:
    wt = wt_root / name
    wt.mkdir(parents=True)
    (wt / ".git").write_text(f"gitdir: /fake/.git/worktrees/{name}\n")
    mtime = _time.time() - age_secs
    os.utime(wt, (mtime, mtime))
    return wt


# ── shell-port-worktree-prune tests ──────────────────────────────────────────


def test_prune_runs_at_session_end_not_start(tmp_path, monkeypatch):
    """_prune_stale_worktrees called after _land_all; _prune_stale_containers called before."""
    orchestrate = _load("orchestrate")
    _load("land_queue")
    _load("scheduler")

    call_order: list[str] = []

    def fake_drain(chunks, **kw):
        call_order.append("land")
        return [{"slug": c.slug, "status": "success"} for c in chunks]

    monkeypatch.setattr(orchestrate, "_prune_stale_containers", lambda: call_order.append("containers"))
    monkeypatch.setattr(orchestrate, "_prune_stale_worktrees", lambda: call_order.append("worktrees"))
    monkeypatch.setattr(orchestrate, "_fan_out_plans", lambda plans, **kw: [p.slug for p in plans])
    monkeypatch.setattr(orchestrate._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._batch_review, "review", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    orchestrate.run_orchestrate(
        "holding",
        _make_plans(tmp_path),
        harness=None,
        model=None,
        dry_run=False,
    )

    assert "worktrees" in call_order, "_prune_stale_worktrees not called"
    assert "containers" in call_order, "_prune_stale_containers not called"
    assert "land" in call_order, "_land_all not called"
    containers_pos = call_order.index("containers")
    land_pos = call_order.index("land")
    worktrees_pos = call_order.index("worktrees")
    assert containers_pos < land_pos, "containers prune must come before land"
    assert worktrees_pos > land_pos, "worktrees prune must come after land"


def test_prune_removes_old_clean_orphan(tmp_path, monkeypatch):
    """Stale clean mentat-* worktree is removed by _prune_stale_worktrees."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-12-34", age_secs=7200)

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_worktrees()

    assert not wt.exists(), "stale clean orphan must be removed"


def test_prune_skips_dirty_orphan(tmp_path, monkeypatch):
    """Stale but dirty worktree is preserved."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-55-66", age_secs=7200)
    (wt / "dirty.txt").write_text("uncommitted\n")
    # Re-stamp mtime — writing the file resets the dir mtime to now
    os.utime(wt, (_time.time() - 7200, _time.time() - 7200))

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "?? dirty.txt\n")  # dirty
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_worktrees()

    assert wt.exists(), "dirty orphan must be preserved"


def test_prune_skips_recent(tmp_path, monkeypatch):
    """Worktree newer than 1h is not pruned even if clean."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-77-88", age_secs=300)  # 5 min ago

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp_proc(0, ""))

    orchestrate._prune_stale_worktrees()

    assert wt.exists(), "recent worktree must not be pruned"


def test_prune_skips_active(tmp_path, monkeypatch):
    """Worktree whose slug is in list_active_slugs is not pruned."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    slug = "mentat-1700000000-99-11"
    wt = _make_wt(wt_root, slug, age_secs=7200)

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: {slug})
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp_proc(0, ""))

    orchestrate._prune_stale_worktrees()

    assert wt.exists(), "active worktree must not be pruned"


def test_prune_is_path_based_not_name_based(tmp_path, monkeypatch):
    """Identity is path, not name (S1 landmine fix): a clean stale worktree is
    pruned regardless of its name — including one the legacy mentat-manual-*
    name-exemption would have spared."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = wt_root / "mentat-manual-my-task"  # formerly exempt by name
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /fake\n")
    mtime = _time.time() - 7200
    os.utime(wt, (mtime, mtime))

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_worktrees()

    assert not wt.exists(), "name-exemption is gone — clean stale pruned by path"


def test_prune_falls_back_to_rmtree(tmp_path, monkeypatch):
    """When git worktree remove fails, shutil.rmtree removes the dir."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-22-33", age_secs=7200)

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            return _cp_proc(1)  # fail → triggers shutil.rmtree fallback
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_worktrees()

    assert not wt.exists(), "rmtree fallback must remove dir when git worktree remove fails"


def test_prune_emits_session_prune_event(tmp_path, monkeypatch):
    """_prune_stale_worktrees emits exactly one session.prune with worktrees_removed key."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    _make_wt(wt_root, "mentat-1700000000-44-55", age_secs=7200)

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())

    emit_calls: list[tuple] = []
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda ev, p: emit_calls.append((ev, p)))

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_worktrees()

    prune_events = [(ev, p) for ev, p in emit_calls if ev == "session.prune"]
    assert len(prune_events) == 1, f"expected exactly one session.prune; got {prune_events}"
    payload = prune_events[0][1]
    assert "worktrees_removed" in payload, f"session.prune missing worktrees_removed; payload={payload}"
    assert payload["worktrees_removed"] == 1


def test_container_prune_inherits_dirty_check(tmp_path, monkeypatch):
    """If any stale worktree under .mentat/worktrees/ is dirty, devcontainer.prune is not called."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-66-77", age_secs=7200)
    (wt / "dirty.txt").write_text("uncommitted\n")
    # Re-stamp mtime — writing the file resets the dir mtime to now
    os.utime(wt, (_time.time() - 7200, _time.time() - 7200))

    prune_calls: list[int] = []
    monkeypatch.setattr(_dc_mod, "prune", lambda: prune_calls.append(1) or PruneResult(None, 0))

    emit_calls: list[tuple] = []
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda ev, p: emit_calls.append((ev, p)))

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "?? dirty.txt\n")  # dirty
        return _cp_proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    orchestrate._prune_stale_containers()

    assert prune_calls == [], f"devcontainer.prune must not be called when dirty worktrees exist; got {prune_calls}"


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
