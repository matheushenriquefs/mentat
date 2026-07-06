"""run_orchestrate prunes stale labeled containers at session start and stale
worktrees at session end with dirty-check.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import time as _time
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"
_AGENTS_ROOT = Path(__file__).resolve().parents[3]  # .agents/
from lib import devcontainer as _dc_mod  # noqa: E402

from tests.conftest import TEST_CHUNK_ID, bind_plan, chunk_label, patch_orchestrate_worktree  # noqa: E402


def _seed_run_chunks(orchestrate, *slugs: str) -> None:
    orchestrate._supervise._run_chunk_slugs.clear()
    for slug in slugs:
        bind_plan(slug, TEST_CHUNK_ID)
        orchestrate._supervise._run_chunk_slugs.add(chunk_label(slug))


def _seed_flat_run_chunk(orchestrate, name: str) -> None:
    orchestrate._supervise._run_chunk_slugs.clear()
    orchestrate._supervise._run_chunk_slugs.add(name)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_plans(tmp_path: Path) -> list[Path]:
    p = tmp_path / "a.md"
    p.write_text("---\nid: a\nstatus: ready\nkind: AFK\nblocked_by: []\n---\n# a\n")
    return [p]


def test_run_orchestrate_prunes_before_fanout(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    prune_called_before: list[bool] = []
    fan_out_called: list[bool] = []

    def fake_prune():
        prune_called_before.append(not fan_out_called)

    def fake_fan_out(plans, *, harness=None, model=None):
        fan_out_called.append(True)
        for p in plans:
            _seed_run_chunks(orchestrate, p.slug)
        return [(p, 0) for p in plans]

    monkeypatch.setattr(orchestrate._batch, "_prune_stale_containers", fake_prune)
    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(
        orchestrate._batch._land_queue,
        "drain",
        lambda chunks, **kw: [{"slug": c.slug, "status": "success"} for c in chunks],
    )
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "ensure_agent", lambda *a, **k: "orch-test")
    monkeypatch.setattr(orchestrate._git, "require_commit_identity", lambda **kw: ("T", "t@t"))

    with patch_orchestrate_worktree(orchestrate, tmp_path):
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

    monkeypatch.setattr(orchestrate._batch, "_prune_stale_containers", fake_prune)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

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
    _seed_run_chunks(orchestrate, "a")

    emit_calls: list[tuple] = []
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda ev, payload: emit_calls.append((ev, payload)))
    monkeypatch.setattr(_dc_mod, "down_run", lambda slugs: 2)

    orchestrate._batch._prune_stale_containers()

    assert emit_calls == [("agent_reaped", {"reclaimed_bytes": None, "containers_removed": 2})]


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


# ── worktree prune helpers ────────────────────────────────────────────────────


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


# ── worktree prune tests ──────────────────────────────────────────────────────


def test_prune_runs_at_session_end_not_start(tmp_path, monkeypatch):
    """_prune_stale_worktrees called after _land_all; _prune_stale_containers called before."""
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    call_order: list[str] = []

    def fake_drain(chunks, **kw):
        call_order.append("land")
        return [{"slug": c.slug, "status": "success"} for c in chunks]

    monkeypatch.setattr(orchestrate._batch, "_prune_stale_containers", lambda: call_order.append("containers"))
    monkeypatch.setattr(orchestrate._batch, "_prune_stale_worktrees", lambda **kw: call_order.append("worktrees"))

    def fake_fan_out(plans, **kw):
        for p in plans:
            _seed_run_chunks(orchestrate, p.slug)
        return [(p, 0) for p in plans]

    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(orchestrate._batch._land_queue, "drain", fake_drain)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    with patch_orchestrate_worktree(orchestrate, tmp_path):
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
    """Stale clean worktree is removed by _prune_stale_worktrees when in run scope."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    name = "mentat-1700000000-12-34"
    wt = _make_wt(wt_root, name, age_secs=7200)
    _seed_flat_run_chunk(orchestrate, name)

    monkeypatch.setattr(_dc_mod, "list_active_slugs", lambda: set())
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(orchestrate._batch._worktrees, "is_dirty", lambda _p: False)

    def fake_remove(p: Path) -> bool:
        shutil.rmtree(p, ignore_errors=True)
        return not p.exists()

    monkeypatch.setattr(orchestrate._batch._worktrees, "_remove", fake_remove)

    orchestrate._batch._prune_stale_worktrees()

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

    monkeypatch.setattr(orchestrate._batch._worktrees, "is_dirty", lambda _p: False)

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

    orchestrate._batch._prune_stale_worktrees()

    assert wt.exists(), "recent worktree must not be pruned"


def test_prune_skips_active(tmp_path, monkeypatch):
    """Worktree in preserve set is not pruned."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    slug = "mentat-1700000000-99-11"
    wt = _make_wt(wt_root, slug, age_secs=7200)
    _seed_flat_run_chunk(orchestrate, slug)

    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _cp_proc(0, ""))

    orchestrate._batch._prune_stale_worktrees(preserve={slug})

    assert wt.exists(), "active worktree must not be pruned"


def test_prune_is_path_based_not_name_based(tmp_path, monkeypatch):
    """Identity is path, not name: a clean stale worktree is pruned regardless
    of its name — including one the legacy mentat-manual-* name-exemption
    would have spared."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-manual-my-task", age_secs=7200)
    _seed_flat_run_chunk(orchestrate, "mentat-manual-my-task")

    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(orchestrate._batch._worktrees, "is_dirty", lambda _p: False)

    def fake_remove(p: Path) -> bool:
        shutil.rmtree(p, ignore_errors=True)
        return not p.exists()

    monkeypatch.setattr(orchestrate._batch._worktrees, "_remove", fake_remove)
    orchestrate._batch._prune_stale_worktrees()

    assert not wt.exists(), "name-exemption is gone — clean stale pruned by path"


def test_prune_falls_back_to_rmtree(tmp_path, monkeypatch):
    """When git worktree remove fails, shutil.rmtree removes the dir."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-22-33", age_secs=7200)
    _seed_flat_run_chunk(orchestrate, "mentat-1700000000-22-33")

    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")  # clean
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            return _cp_proc(1)  # fail → triggers shutil.rmtree fallback
        return _cp_proc(0)

    monkeypatch.setattr(orchestrate._batch._worktrees, "is_dirty", lambda _p: False)
    monkeypatch.setattr(subprocess, "run", fake_run)
    orchestrate._batch._prune_stale_worktrees()

    assert not wt.exists(), "rmtree fallback must remove dir when git worktree remove fails"


def test_prune_emits_session_prune_event(tmp_path, monkeypatch):
    """_prune_stale_worktrees emits exactly one agent_reaped with worktrees_removed key."""
    orchestrate = _load("orchestrate")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    name = "mentat-1700000000-44-55"
    _make_wt(wt_root, name, age_secs=7200)
    _seed_flat_run_chunk(orchestrate, name)

    emit_calls: list[tuple] = []
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda ev, p: emit_calls.append((ev, p)))

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return _cp_proc(0, "")
        if cmd[0] == "git" and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(Path(cmd[-1]), ignore_errors=True)
            return _cp_proc(0)
        return _cp_proc(0)

    monkeypatch.setattr(orchestrate._batch._worktrees, "is_dirty", lambda _p: False)

    def fake_remove(p: Path) -> bool:
        shutil.rmtree(p, ignore_errors=True)
        return not p.exists()

    monkeypatch.setattr(orchestrate._batch._worktrees, "_remove", fake_remove)
    orchestrate._batch._prune_stale_worktrees()

    prune_events = [(ev, p) for ev, p in emit_calls if ev == "agent_reaped"]
    assert len(prune_events) == 1, f"expected exactly one agent_reaped; got {prune_events}"
    payload = prune_events[0][1]
    assert "worktrees_removed" in payload, f"agent_reaped missing worktrees_removed; payload={payload}"
    assert payload["worktrees_removed"] == 1


def test_container_prune_runs_even_with_dirty_worktree(tmp_path, monkeypatch):
    """Run-scoped container down runs even when dirty worktrees exist."""
    orchestrate = _load("orchestrate")
    _seed_run_chunks(orchestrate, "a")
    monkeypatch.chdir(tmp_path)

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-1700000000-66-77", age_secs=7200)
    (wt / "dirty.txt").write_text("uncommitted\n")
    os.utime(wt, (_time.time() - 7200, _time.time() - 7200))

    down_calls: list[set[str]] = []
    monkeypatch.setattr(_dc_mod, "down_run", lambda slugs: down_calls.append(set(slugs)) or 1)
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    orchestrate._batch._prune_stale_containers()

    assert down_calls, "devcontainer.down_run must be called even when dirty worktrees exist"


# ── S4: crash-safe teardown + preserved-worktree GC ──────────────────────────


def test_run_orchestrate_prunes_worktrees_even_on_exception(tmp_path, monkeypatch):
    """A mid-batch exception must still run the end-of-batch prune + GC (finally)."""
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    calls: list[str] = []
    monkeypatch.setattr(orchestrate._batch, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orchestrate._batch, "_prune_stale_worktrees", lambda **kw: calls.append("prune"))
    monkeypatch.setattr(orchestrate._batch, "_gc_preserved_worktrees", lambda **kw: calls.append("gc"))
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)

    def boom(plans, **kw):
        raise RuntimeError("fan-out blew up mid-batch")

    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", boom)

    import pytest

    with pytest.raises(RuntimeError):
        orchestrate.run_orchestrate("holding", _make_plans(tmp_path), harness=None, model=None, dry_run=False)

    assert "prune" in calls, "worktree prune must run even when the batch raises"
    assert "gc" in calls, "preserved-worktree GC must run even when the batch raises"


def test_gc_preserved_reclaims_old_dirty_worktree(tmp_path):
    """worktrees.gc_preserved force-removes a dirty worktree older than the GC age."""
    from lib import worktrees

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-ejected-old", age_secs=8 * 24 * 3600)  # 8 days
    (wt / "dirty.txt").write_text("un-landed work\n")
    os.utime(wt, (_time.time() - 8 * 24 * 3600, _time.time() - 8 * 24 * 3600))

    reclaimed = worktrees.gc_preserved(wt_root, gc_seconds=7 * 24 * 3600)

    assert reclaimed == 1
    assert not wt.exists(), "abandoned dirty worktree past the GC age must be reclaimed"


def test_gc_preserved_keeps_recent_dirty_worktree(tmp_path):
    """A dirty worktree younger than the GC age is preserved (operator may resume it)."""
    from lib import worktrees

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-ejected-fresh", age_secs=3600)  # 1h
    (wt / "dirty.txt").write_text("un-landed work\n")
    os.utime(wt, (_time.time() - 3600, _time.time() - 3600))

    reclaimed = worktrees.gc_preserved(wt_root, gc_seconds=7 * 24 * 3600)

    assert reclaimed == 0
    assert wt.exists(), "a recent preserved worktree must survive the GC"


def test_gc_preserved_not_counted_when_remove_fails(tmp_path, monkeypatch):
    """An old worktree whose removal fails is not counted — the loop continues
    past it rather than incrementing (worktrees.py branch 118->115)."""
    from lib import worktrees

    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = _make_wt(wt_root, "mentat-ejected-stuck", age_secs=8 * 24 * 3600)
    (wt / "dirty.txt").write_text("un-landed work\n")
    os.utime(wt, (_time.time() - 8 * 24 * 3600, _time.time() - 8 * 24 * 3600))

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", ""))
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)  # dir stays → _remove returns False

    assert worktrees.gc_preserved(wt_root, gc_seconds=7 * 24 * 3600) == 0
    assert wt.exists()


def test_gc_preserved_spares_active_slug(tmp_path):
    """An old worktree whose slug is active is never GC'd."""
    from lib import worktrees

    wt_root = tmp_path / ".mentat" / "worktrees"
    slug = "mentat-active-old"
    wt = _make_wt(wt_root, slug, age_secs=8 * 24 * 3600)
    os.utime(wt, (_time.time() - 8 * 24 * 3600, _time.time() - 8 * 24 * 3600))

    reclaimed = worktrees.gc_preserved(wt_root, active_slugs={slug}, gc_seconds=7 * 24 * 3600)

    assert reclaimed == 0
    assert wt.exists(), "active worktree must not be GC'd"


def test_prune_failure_does_not_abort(tmp_path, monkeypatch):
    orchestrate = _load("orchestrate")
    _load("landing")
    _load("scheduler")

    def fake_subprocess_run(cmd, **kw):
        class _R:
            returncode = 1
            stdout = ""
            stderr = ""
            stdout = ""

        return _R()

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(orchestrate._utils, "read_config", lambda: {})
    monkeypatch.setattr(orchestrate._batch, "_run_recovery", lambda *a, **k: (set(), set(), set()))

    def fake_fan_out(plans, **kw):
        for p in plans:
            _seed_run_chunks(orchestrate, p.slug)
        return [(p, 0, None, None) for p in plans]

    monkeypatch.setattr(orchestrate._batch, "_fan_out_plans", fake_fan_out)
    monkeypatch.setattr(
        orchestrate._batch._land_queue,
        "drain",
        lambda chunks, **kw: [{"slug": c.slug, "status": "success"} for c in chunks],
    )
    monkeypatch.setattr(orchestrate._utils, "emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orchestrate, "ensure_agent", lambda *a, **k: "orch-test")
    monkeypatch.setattr(orchestrate._git, "require_commit_identity", lambda **kw: ("T", "t@t"))

    with patch_orchestrate_worktree(orchestrate, tmp_path):
        rc = orchestrate.run_orchestrate(
            "holding",
            _make_plans(tmp_path),
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 0, "orchestrate must complete even when prune subprocess fails"
