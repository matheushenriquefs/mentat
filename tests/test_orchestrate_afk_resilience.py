"""Tests for mentat-afk-resilience-orchestrate slices 1-6.

Slice 1: _partition_fanout is total — rc=1/69/70 → eject not land.
Slice 2: _fan_out_plans kills hung child after deadline, returns rc<0.
Slice 3: _spawn_batch_doctor argv parses cleanly (no --reason).
Slice 4: run_orchestrate names ejected chunks on stdout.
Slice 5: _prune_stale_containers runs even with dirty worktrees.
Slice 6: _SIGNAL_EXIT_BASE = 128 module constant.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan(tmp_path: Path, slug: str, class_: str = "AFK"):
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nclass: {class_}\n---\n")
    return p


def _make_plan_obj(tmp_path: Path, slug: str, class_: str = "AFK"):
    routing = load_module("scheduler")
    path = _make_plan(tmp_path, slug, class_)
    return routing.Plan(slug=slug, class_=class_, blocked_by=[], path=path)


# ── Slice 6: _SIGNAL_EXIT_BASE constant ──────────────────────────────────────


def test_signal_exit_base_constant_is_128():
    orch = load_module("orchestrate")
    assert orch._SIGNAL_EXIT_BASE == 128, "_SIGNAL_EXIT_BASE must equal 128"


# ── Slice 1: _partition_fanout totality ──────────────────────────────────────


def _run_partition(tmp_path, rc: int) -> tuple[list, set]:
    """Helper: run _partition_fanout with a single plan returning rc."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-a")
    ejected: list[str] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch, "_emit_event", lambda *a, **k: None):
            chunks, hitl = orch._partition_fanout(
                [(plan, rc)],
                mark_ejected=lambda slug: ejected.append(slug) or [],
            )
    return chunks, hitl


def test_partition_fanout_rc_0_is_landable(tmp_path):
    chunks, hitl = _run_partition(tmp_path, 0)
    assert len(chunks) == 1, "rc=0 must be landable"
    assert len(hitl) == 0


def test_partition_fanout_rc_42_is_hitl(tmp_path):
    chunks, hitl = _run_partition(tmp_path, 42)
    assert len(chunks) == 0, "rc=42 (HITL_REQUIRED) must not land"
    assert "slug-a" in hitl


def test_partition_fanout_rc_1_ejects_not_lands(tmp_path):
    """rc=1 (EX_FAILURE) must → eject, not land (Slice 1 fix)."""
    chunks, hitl = _run_partition(tmp_path, 1)
    assert len(chunks) == 0, "rc=1 must be ejected, not landable"


def test_partition_fanout_rc_69_ejects_not_lands(tmp_path):
    """rc=69 (EX_UNAVAILABLE / container down) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 69)
    assert len(chunks) == 0, "rc=69 must be ejected, not landable"


def test_partition_fanout_rc_70_ejects_not_lands(tmp_path):
    """rc=70 (EX_SOFTWARE) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 70)
    assert len(chunks) == 0, "rc=70 must be ejected, not landable"


def test_partition_fanout_rc_65_ejects_not_lands(tmp_path):
    """rc=65 (EX_DATAERR / malformed plan) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 65)
    assert len(chunks) == 0, "rc=65 must be ejected, not landable"


def test_partition_fanout_rc_signal_ejects(tmp_path):
    """rc=-9 (signal kill) must → eject with WORKER_DIED."""
    chunks, hitl = _run_partition(tmp_path, -9)
    assert len(chunks) == 0, "rc=-9 must be ejected"


def test_partition_fanout_rc_128plus_ejects(tmp_path):
    """rc=130 (128+signum) must → eject with WORKER_DIED."""
    chunks, hitl = _run_partition(tmp_path, 130)
    assert len(chunks) == 0, "rc=130 must be ejected"


def test_partition_fanout_rc_69_emits_ejection(tmp_path):
    """rc=69 must emit chunk.ejected event."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-b")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._partition_fanout(
                [(plan, 69)],
                mark_ejected=lambda slug: [],
            )

    assert any(ev == "chunk.ejected" for ev, _ in emitted), "rc=69 must emit chunk.ejected"


def test_partition_fanout_rc_1_reason_is_implement_failed(tmp_path):
    """rc=1 eject reason must be implement-failed, not worker-died."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-c")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._partition_fanout(
                [(plan, 1)],
                mark_ejected=lambda slug: [],
            )

    eject_events = [(ev, p) for ev, p in emitted if ev == "chunk.ejected"]
    assert eject_events, "rc=1 must emit chunk.ejected"
    reason = eject_events[0][1].get("reason")
    assert reason == "implement-failed", f"rc=1 reason must be implement-failed, got {reason!r}"


def test_partition_fanout_rc_69_reason_is_worker_died(tmp_path):
    """rc=69 eject reason must be worker-died (infra failure)."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-d")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._partition_fanout(
                [(plan, 69)],
                mark_ejected=lambda slug: [],
            )

    eject_events = [(ev, p) for ev, p in emitted if ev == "chunk.ejected"]
    reason = eject_events[0][1].get("reason")
    assert reason == "worker-died", f"rc=69 reason must be worker-died, got {reason!r}"


# ── Slice 2: per-chunk wall-clock deadline ────────────────────────────────────


class _HangingPopen:
    """Popen stub that never exits (simulates a wedged child)."""

    returncode: int | None = None

    def poll(self) -> int | None:
        return None  # never exits during poll

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None:
            raise subprocess.TimeoutExpired("cmd", timeout)
        import time

        time.sleep(9999)
        return 0  # unreachable in test

    def terminate(self) -> None:
        self.returncode = -15  # SIGTERM

    def kill(self) -> None:
        self.returncode = -9  # SIGKILL


def test_chunk_timeout_default_is_1800(monkeypatch):
    """Default chunk_timeout is 1800s (30 min) when not configured."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._chunk_timeout() == 1800


def test_chunk_timeout_reads_config(monkeypatch):
    """chunk_timeout reads from config file."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 600})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._chunk_timeout() == 600


def test_chunk_timeout_env_overrides_config(monkeypatch):
    """MENTAT_CHUNK_TIMEOUT env overrides config value."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 600})
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "120")
    assert orch._chunk_timeout() == 120


def test_chunk_timeout_clamps_to_min_1(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 0})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._chunk_timeout() >= 1


def test_fan_out_plans_kills_hung_child_within_deadline(monkeypatch, tmp_path):
    """A hung child must be killed and return rc<0 within the deadline."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = routing.Plan(slug="hung", class_="AFK", blocked_by=[], path=tmp_path / "hung.md")
    fake_proc = _HangingPopen()

    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 1, "chunk_timeout": 1})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    monkeypatch.setattr(orch._fan_out, "spawn_with_proc", lambda *a, **k: ("sess-hung", fake_proc))
    monkeypatch.setattr(orch.time, "sleep", lambda _s: None)

    results = orch._fan_out_plans([plan], harness=None, model=None)

    assert len(results) == 1
    _p, rc = results[0]
    assert rc is not None and rc < 0, f"hung child must be killed (rc<0), got rc={rc}"


def test_fan_out_plans_killed_child_ejects_worker_died(monkeypatch, tmp_path):
    """A killed child (rc<0) → _partition_fanout routes to WORKER_DIED."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = routing.Plan(slug="timed-out", class_="AFK", blocked_by=[], path=tmp_path / "p.md")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            chunks, _ = orch._partition_fanout(
                [(plan, -9)],
                mark_ejected=lambda slug: [],
            )

    assert len(chunks) == 0
    eject = [p for ev, p in emitted if ev == "chunk.ejected"]
    assert eject and eject[0]["reason"] == "worker-died"


# ── Slice 3: doctor handoff argv parses cleanly ───────────────────────────────


def test_spawn_batch_doctor_argv_parses_cleanly():
    """argv built by _spawn_batch_doctor must parse without argparse error."""
    orch = load_module("orchestrate")
    session_script = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-session/scripts/session.py"
    if not session_script.exists():
        import pytest

        pytest.skip("session.py not found")

    session_mod = load_script(session_script, "session_for_test")
    parser = session_mod.build_parser()

    # Simulate what _spawn_batch_doctor builds: ["python3", "session.py", "doctor"]
    # (no --reason= flag after the fix)
    captured_argv: list[list[str]] = []

    def fake_popen(argv, **kwargs):
        captured_argv.append(argv)
        raise OSError("intercepted")  # suppress actual spawn

    with patch.object(orch.subprocess, "Popen", fake_popen):
        with patch("pathlib.Path.exists", return_value=True):
            orch._spawn_batch_doctor()

    assert captured_argv, "Popen must have been called"
    argv = captured_argv[0]
    # Find "doctor" and everything after
    try:
        doc_idx = argv.index("doctor")
    except ValueError:
        raise AssertionError(f"'doctor' not in argv: {argv}") from None

    sub_argv = argv[doc_idx:]  # ["doctor", ...]
    # Must parse cleanly — no SystemExit
    try:
        parser.parse_args(sub_argv)
    except SystemExit as e:
        raise AssertionError(
            f"doctor argv {sub_argv!r} fails to parse (exit {e.code}): likely --reason= present"
        ) from e


def test_spawn_batch_doctor_no_reason_flag():
    """_spawn_batch_doctor must NOT pass --reason to doctor subcommand."""
    orch = load_module("orchestrate")

    captured_argv: list[list[str]] = []

    def fake_popen(argv, **kwargs):
        captured_argv.append(argv)
        raise OSError("intercepted")

    with patch.object(orch.subprocess, "Popen", fake_popen):
        with patch("pathlib.Path.exists", return_value=True):
            orch._spawn_batch_doctor()

    if not captured_argv:
        return  # Popen wasn't reached (session.py missing) — skip

    argv = captured_argv[0]
    assert not any("--reason" in a for a in argv), f"--reason must not appear in argv: {argv}"


# ── Slice 4: eject summary on stdout ─────────────────────────────────────────


def test_run_orchestrate_names_ejected_chunks_on_failure(tmp_path, capsys):
    """A batch with at least one ejected chunk must name the slug+reason on stderr."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = _make_plan(tmp_path, "fail-slug", "AFK")
    plan_obj = routing.Plan(slug="fail-slug", class_="AFK", blocked_by=[], path=plan)

    with (
        patch.object(orch, "_fan_out_plans", return_value=[(plan_obj, 1)]),
        patch.object(orch, "_worktree_for_slug", return_value=tmp_path),
        patch.object(orch._land_queue, "drain", return_value=[]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", lambda: None),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[plan],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 1
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "fail-slug" in output, f"ejected slug must appear in output; got: {output!r}"


def test_run_orchestrate_all_green_no_eject_summary(tmp_path, capsys):
    """All-green batch must not print eject-summary lines."""
    orch = load_module("orchestrate")

    plan = _make_plan(tmp_path, "ok-slug", "AFK")

    with (
        patch.object(orch, "_fan_out_plans", return_value=[]),
        patch.object(orch._land_queue, "drain", return_value=[{"slug": "ok-slug", "status": "success"}]),
        patch.object(orch, "_prune_stale_containers", lambda: None),
        patch.object(orch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch, "_spawn_batch_doctor", lambda: None),
    ):
        rc = orch.run_orchestrate(
            holding="main",
            plan_paths=[plan],
            harness=None,
            model=None,
            dry_run=False,
        )

    assert rc == 0
    captured = capsys.readouterr()
    output = captured.err + captured.out
    assert "ejected" not in output.lower(), f"no eject summary on green batch; got: {output!r}"


# ── Slice 5: prune runs even with dirty worktrees ────────────────────────────


def test_prune_stale_containers_runs_even_with_dirty_worktree(tmp_path, monkeypatch):
    """_prune_stale_containers must call devcontainer.prune() even if dirty worktrees exist."""
    import os
    import time as _time

    orch = load_module("orchestrate")
    from lib import devcontainer as _dc_mod
    from lib.devcontainer import PruneResult

    monkeypatch.chdir(tmp_path)
    # Create a dirty stale worktree
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = wt_root / "mentat-1700000000-12-34"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /fake\n")
    (wt / "dirty.txt").write_text("uncommitted\n")
    mtime = _time.time() - 7200
    os.utime(wt, (mtime, mtime))

    prune_calls = [0]
    monkeypatch.setattr(
        _dc_mod, "prune", lambda: prune_calls.__setitem__(0, prune_calls[0] + 1) or PruneResult(None, 0)
    )
    monkeypatch.setattr(orch._utils, "emit_event", lambda *a, **k: None)

    def fake_run(cmd, **kw):
        if cmd[0] == "git" and "status" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "?? dirty.txt\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    orch._prune_stale_containers()

    assert prune_calls[0] == 1, "devcontainer.prune must be called even when dirty worktrees exist"
