"""Tests for mentat-afk-resilience-orchestrate slices 1-5.

Slice 1: partition_by_outcome is total — rc=1/69/70 → eject not land.
Slice 2: _fan_out_plans kills hung child after deadline, returns rc<0.
Slice 3: run_orchestrate names ejected chunks on stdout.
Slice 4: _prune_stale_containers runs even with dirty worktrees.
Slice 5: _SIGNAL_EXIT_BASE = 128 module constant.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import async_spawner, bind_plan, chunk_label, load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan(tmp_path: Path, slug: str, kind: str = "AFK"):
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nkind: {kind}\n---\n")
    return p


def _make_plan_obj(tmp_path: Path, slug: str, kind: str = "AFK"):
    routing = load_module("scheduler")
    path = _make_plan(tmp_path, slug, kind)
    return routing.Plan(slug=slug, kind=kind, blocked_by=[], path=path)


# ── Slice 5: _SIGNAL_EXIT_BASE constant ──────────────────────────────────────


def test_signal_exit_base_constant_is_128():
    orch = load_module("orchestrate")
    assert orch._batch._SIGNAL_EXIT_BASE == 128, "_SIGNAL_EXIT_BASE must equal 128"


# ── Slice 1: partition_by_outcome totality ──────────────────────────────────────


def _run_partition(tmp_path, rc: int) -> tuple[list, set]:
    """Helper: run partition_by_outcome with a single plan returning rc."""
    orch = load_module("orchestrate")
    bind_plan("slug-a")
    plan = _make_plan_obj(tmp_path, "slug-a")
    ejected: list[str] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda *a, **k: None):
            chunks, hitl, _transient = orch._batch.partition_by_outcome(
                [(plan, rc)],
                mark_ejected=lambda slug: ejected.append(slug) or [],
            )
    return chunks, hitl


def testpartition_by_outcome_rc_0_is_landable(tmp_path):
    chunks, hitl = _run_partition(tmp_path, 0)
    assert len(chunks) == 1, "rc=0 must be landable"
    assert len(hitl) == 0


def testpartition_by_outcome_rc_42_is_hitl(tmp_path):
    chunks, hitl = _run_partition(tmp_path, 42)
    assert len(chunks) == 0, "rc=42 (HITL_REQUIRED) must not land"
    assert "slug-a" in hitl


def testpartition_by_outcome_rc_1_ejects_not_lands(tmp_path):
    """rc=1 (EX_FAILURE) must → eject, not land (Slice 1 fix)."""
    chunks, hitl = _run_partition(tmp_path, 1)
    assert len(chunks) == 0, "rc=1 must be ejected, not landable"


def testpartition_by_outcome_rc_69_ejects_not_lands(tmp_path):
    """rc=69 (EX_UNAVAILABLE / container down) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 69)
    assert len(chunks) == 0, "rc=69 must be ejected, not landable"


def testpartition_by_outcome_rc_70_ejects_not_lands(tmp_path):
    """rc=70 (EX_SOFTWARE) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 70)
    assert len(chunks) == 0, "rc=70 must be ejected, not landable"


def testpartition_by_outcome_rc_65_ejects_not_lands(tmp_path):
    """rc=65 (EX_DATAERR / malformed plan) must → eject, not land."""
    chunks, hitl = _run_partition(tmp_path, 65)
    assert len(chunks) == 0, "rc=65 must be ejected, not landable"


def testpartition_by_outcome_rc_signal_ejects(tmp_path):
    """rc=-9 (signal kill) must → eject with WORKER_DIED."""
    chunks, hitl = _run_partition(tmp_path, -9)
    assert len(chunks) == 0, "rc=-9 must be ejected"


def testpartition_by_outcome_rc_128plus_ejects(tmp_path):
    """rc=130 (128+signum) must → eject with WORKER_DIED."""
    chunks, hitl = _run_partition(tmp_path, 130)
    assert len(chunks) == 0, "rc=130 must be ejected"


def testpartition_by_outcome_rc_69_emits_ejection(tmp_path):
    """rc=69 must emit chunk_ejected event."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-b")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._batch.partition_by_outcome(
                [(plan, 69)],
                mark_ejected=lambda slug: [],
            )

    assert any(ev == "chunk_ejected" for ev, _ in emitted), "rc=69 must emit chunk_ejected"


def testpartition_by_outcome_rc_1_reason_is_implement_failed(tmp_path):
    """rc=1 eject reason must be implement-failed, not worker-died."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-c")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._batch.partition_by_outcome(
                [(plan, 1)],
                mark_ejected=lambda slug: [],
            )

    eject_events = [(ev, p) for ev, p in emitted if ev == "chunk_ejected"]
    assert eject_events, "rc=1 must emit chunk_ejected"
    reason = eject_events[0][1].get("reason")
    assert reason == "implement_failed", f"rc=1 reason must be implement-failed, got {reason!r}"


def testpartition_by_outcome_rc_69_reason_is_worker_died(tmp_path):
    """rc=69 eject reason must be worker-died (infra failure)."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-d")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, payload: emitted.append((ev, payload))):
            orch._batch.partition_by_outcome(
                [(plan, 69)],
                mark_ejected=lambda slug: [],
            )

    eject_events = [(ev, p) for ev, p in emitted if ev == "chunk_ejected"]
    reason = eject_events[0][1].get("reason")
    assert reason == "worker_died", f"rc=69 reason must be worker-died, got {reason!r}"


# ── S2: worker-died is self-describing (timed_out / killed_by + logs_path) ────


def testpartition_by_outcome_timeout_kill_payload_is_self_describing(tmp_path):
    """A timeout-killed chunk (rc<0) → payload timed_out:true + logs_path at its
    own session dir."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-t")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            orch._batch.partition_by_outcome(
                [(plan, -9, "/logs/sess-t")],
                mark_ejected=lambda slug: [],
            )

    p = [p for ev, p in emitted if ev == "chunk_ejected"][0]
    assert p["reason"] == "worker_died"
    assert p["timed_out"] is True
    assert p["logs_path"] == "/logs/sess-t"


def testpartition_by_outcome_container_down_payload_names_killer(tmp_path):
    """A container-down chunk (rc69) → payload killed_by:'container-down' + logs_path."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "slug-cd")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            orch._batch.partition_by_outcome(
                [(plan, 69, "/logs/sess-cd")],
                mark_ejected=lambda slug: [],
            )

    p = [p for ev, p in emitted if ev == "chunk_ejected"][0]
    assert p["reason"] == "worker_died"
    assert p["killed_by"] == "container-down"
    assert p["logs_path"] == "/logs/sess-cd"
    assert "timed_out" not in p, "container-down is not a timeout"


# ── S4: partition tears down ejected containers; reaper stops on timeout ──────


def testpartition_by_outcome_tears_down_ejected_container(tmp_path):
    """A partition-ejected chunk → devcontainer.down(slug) + chunk_teardown emitted
    (it never reaches the land queue that normally tears containers down)."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "ej")
    down_calls: list[str] = []
    emitted: list[tuple] = []

    bind_plan("ej")
    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch._devcontainer, "down", lambda slug: down_calls.append(slug) or True):
            with patch.object(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
                orch._batch.partition_by_outcome([(plan, -9, "/logs/ej")], mark_ejected=lambda s: [])

    assert down_calls == [chunk_label("ej")], f"ejected chunk container must be torn down: {down_calls}"
    teardowns = [p for ev, p in emitted if ev == "chunk_teardown"]
    assert teardowns and teardowns[0]["slug"] == "ej"


def test_supervisor_stops_container_on_timeout(monkeypatch, tmp_path):
    """The reaper docker-stops the slug container on a deadline kill so the
    in-container agent (in its own PID namespace) dies."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="hung-c", kind="AFK", blocked_by=[], path=tmp_path / "hung-c.md")

    bind_plan("hung-c")
    down_calls: list[str] = []
    monkeypatch.setattr(orch._batch._devcontainer, "down", lambda slug: down_calls.append(slug) or True)
    monkeypatch.setattr(orch._supervise, "_chunk_timeout", lambda: 0.05)
    monkeypatch.setattr(orch._supervise, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch._supervise._spawn, "spawn_async", _async_spawner([FakeAsyncProc(hang=True)], tmp_path))

    orch._batch._fan_out_plans([plan], harness=None, model=None)

    assert chunk_label("hung-c") in down_calls, f"reaper must docker-stop the timed-out slug: {down_calls}"


# ── Slice 2: per-chunk wall-clock deadline ────────────────────────────────────


class FakeAsyncProc:
    """asyncio.subprocess.Process double for supervisor tests.

    pid=None by default so ``_kill_proc_group`` uses the ``proc.kill()`` fallback
    (no real syscall against a bystander pid). ``hang=True`` makes communicate()
    never return, forcing the per-chunk ``asyncio.timeout`` to fire.
    """

    def __init__(self, *, sleep: float = 0.0, rc: int = 0, hang: bool = False, pid: int | None = None) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self._sleep = sleep
        self._rc = rc
        self._hang = hang

    async def communicate(self):
        import asyncio as _a

        if self._hang:
            await _a.sleep(3600)
        else:
            await _a.sleep(self._sleep)
        self.returncode = self._rc
        return (b"", b"")

    async def wait(self):
        return self.returncode

    def kill(self) -> None:
        if self.returncode is None:  # a finish-in-the-gap exit is not overwritten
            self.returncode = -9


def _async_spawner(procs: list[FakeAsyncProc], worktree: Path):
    return async_spawner(procs, worktree)


def test_chunk_timeout_default_is_1800(monkeypatch):
    """Default chunk_timeout is 1800s (30 min) when not configured."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._supervise._chunk_timeout() == 1800


def test_chunk_timeout_reads_config(monkeypatch):
    """chunk_timeout reads from config file."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 600})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._supervise._chunk_timeout() == 600


def test_chunk_timeout_env_overrides_config(monkeypatch):
    """MENTAT_CHUNK_TIMEOUT env overrides config value."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 600})
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "120")
    assert orch._supervise._chunk_timeout() == 120


def test_chunk_timeout_clamps_to_min_1(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 0})
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    assert orch._supervise._chunk_timeout() >= 1


def test_fan_out_plans_kills_hung_child_within_deadline(monkeypatch, tmp_path):
    """A hung child must be killed and return rc<0 within the deadline."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = routing.Plan(slug="hung", kind="AFK", blocked_by=[], path=tmp_path / "hung.md")

    monkeypatch.setattr(orch._supervise, "_chunk_timeout", lambda: 0.05)
    monkeypatch.setattr(orch._supervise, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch._supervise._spawn, "spawn_async", _async_spawner([FakeAsyncProc(hang=True)], tmp_path))

    results = orch._batch._fan_out_plans([plan], harness=None, model=None)

    assert len(results) == 1
    _p, rc = results[0][0], results[0][1]
    assert rc is not None and rc < 0, f"hung child must be killed (rc<0), got rc={rc}"


def test_fan_out_plans_records_rc_for_finish_in_the_gap(monkeypatch, tmp_path):
    """A chunk that exits in the overdue→kill gap → its real rc is recorded, not
    a kill. FakeAsyncProc hangs (timeout fires) but its returncode was already
    set to 0 by the (simulated) transport, so the kill is a no-op and 0 sticks."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = routing.Plan(slug="gap", kind="AFK", blocked_by=[], path=tmp_path / "gap.md")
    proc = FakeAsyncProc(hang=True)
    proc.returncode = 0  # exited just as the deadline fired

    monkeypatch.setattr(orch._supervise, "_chunk_timeout", lambda: 0.05)
    monkeypatch.setattr(orch._supervise, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch._supervise._spawn, "spawn_async", _async_spawner([proc], tmp_path))

    results = orch._batch._fan_out_plans([plan], harness=None, model=None)
    _p, rc = results[0][0], results[0][1]
    assert rc == 0, f"finish-in-the-gap must record real rc, got {rc}"


def test_fan_out_plans_harvest_order_matches_submission(monkeypatch, tmp_path):
    """N jobs, cap C<N, one hangs → harvest order == submission order; the hung
    chunk is killed at its deadline while the others complete."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plans = [routing.Plan(slug=f"p{i}", kind="AFK", blocked_by=[], path=tmp_path / f"p{i}.md") for i in range(3)]
    procs = [FakeAsyncProc(sleep=0.02, rc=0), FakeAsyncProc(hang=True), FakeAsyncProc(sleep=0.01, rc=0)]

    monkeypatch.setattr(orch._supervise, "_chunk_timeout", lambda: 0.1)
    monkeypatch.setattr(orch._supervise, "_concurrency_cap", lambda: 2)
    monkeypatch.setattr(orch._supervise._spawn, "spawn_async", _async_spawner(procs, tmp_path))

    results = orch._batch._fan_out_plans(plans, harness=None, model=None)

    assert [p.slug for p, *_ in results] == ["p0", "p1", "p2"], "harvest must be in submission order"
    rc_by = {p.slug: rc for p, rc, *_ in results}
    assert rc_by["p1"] is not None and rc_by["p1"] < 0, f"hung p1 must be killed: {rc_by}"
    assert rc_by["p0"] == 0 and rc_by["p2"] == 0, f"healthy chunks must complete: {rc_by}"


def test_fan_out_plans_killed_child_ejects_worker_died(monkeypatch, tmp_path):
    """A killed child (rc<0) → partition_by_outcome routes to WORKER_DIED."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = routing.Plan(slug="timed-out", kind="AFK", blocked_by=[], path=tmp_path / "p.md")
    emitted: list[tuple] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            chunks, _hitl, _transient = orch._batch.partition_by_outcome(
                [(plan, -9)],
                mark_ejected=lambda slug: [],
            )

    assert len(chunks) == 0
    eject = [p for ev, p in emitted if ev == "chunk_ejected"]
    assert eject and eject[0]["reason"] == "worker_died"


# ── S3: partition_by_outcome returns the transient (retryable) set ──────────────


def testpartition_by_outcome_worker_died_is_in_transient_set(tmp_path):
    """A worker-died chunk (timeout / container-down) is returned in the transient
    set — the engine seam — not silently swallowed."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="td", kind="AFK", blocked_by=[], path=tmp_path / "td.md")

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda *a, **k: None):
            chunks, hitl, transient = orch._batch.partition_by_outcome(
                [(plan, -9, "/logs/td")],
                mark_ejected=lambda slug: [],
            )

    assert "td" in transient, "worker-died must be in the transient set"


def testpartition_by_outcome_container_down_is_transient(tmp_path):
    """A container-down chunk (rc69) is transient too."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="cd", kind="AFK", blocked_by=[], path=tmp_path / "cd.md")

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda *a, **k: None):
            _c, _h, transient = orch._batch.partition_by_outcome(
                [(plan, 69, "/logs/cd")],
                mark_ejected=lambda slug: [],
            )
    assert "cd" in transient


def testpartition_by_outcome_implement_failed_stays_terminal(tmp_path):
    """A terminal eject (rc=1 implement-failed) must NOT be in the transient set."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="tf", kind="AFK", blocked_by=[], path=tmp_path / "tf.md")

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda *a, **k: None):
            _c, _h, transient = orch._batch.partition_by_outcome(
                [(plan, 1, "/logs/tf")],
                mark_ejected=lambda slug: [],
            )
    assert "tf" not in transient, "implement-failed is terminal, not transient"


def testpartition_by_outcome_transient_chunks_not_marked_ejected_by_partition(tmp_path):
    """Transient ejects are RETURNED for the caller, not mark_ejected'd inside
    partition — that is the seam the recovery engine owns."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="wd", kind="AFK", blocked_by=[], path=tmp_path / "wd.md")
    marked: list[str] = []

    with patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._batch, "_emit_event", lambda *a, **k: None):
            _c, _h, transient = orch._batch.partition_by_outcome(
                [(plan, -9, "/logs/wd")],
                mark_ejected=lambda slug: marked.append(slug) or [],
            )
    assert "wd" in transient
    assert marked == [], "partition must not mark_ejected transient chunks"


# ── Slice 3: eject summary on stdout ─────────────────────────────────────────


def test_run_orchestrate_names_ejected_chunks_on_failure(tmp_path, capsys):
    """A batch with at least one ejected chunk must name the slug+reason on stderr."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")

    plan = _make_plan(tmp_path, "fail-slug", "AFK")
    plan_obj = routing.Plan(slug="fail-slug", kind="AFK", blocked_by=[], path=plan)

    with (
        patch.object(orch._batch, "_fan_out_plans", return_value=[(plan_obj, 1)]),
        patch.object(orch._batch, "_worktree_for_slug", return_value=tmp_path),
        patch.object(orch._batch._land_queue, "drain", return_value=[]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
        patch.object(orch._batch, "_emit_event", lambda *a, **k: None),
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
        patch.object(orch._batch, "_fan_out_plans", return_value=[]),
        patch.object(orch._batch._land_queue, "drain", return_value=[{"slug": "ok-slug", "status": "success"}]),
        patch.object(orch._batch, "_prune_stale_containers", lambda: None),
        patch.object(orch._batch, "_prune_stale_worktrees", lambda *a, **k: None),
        patch.object(orch._utils, "emit_event", lambda *a, **k: None),
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


# ── Slice 4: prune runs even with dirty worktrees ────────────────────────────


def test_prune_stale_containers_runs_even_with_dirty_worktree(tmp_path, monkeypatch):
    """_prune_stale_containers calls down_run even if dirty worktrees exist."""
    import os
    import time as _time

    orch = load_module("orchestrate")
    from lib import devcontainer as _dc_mod

    from tests.test_orchestrate_prune import _seed_run_chunks

    monkeypatch.chdir(tmp_path)
    _seed_run_chunks(orch, "a")
    wt_root = tmp_path / ".mentat" / "worktrees"
    wt = wt_root / "mentat-1700000000-12-34"
    wt.mkdir(parents=True)
    (wt / ".git").write_text("gitdir: /fake\n")
    (wt / "dirty.txt").write_text("uncommitted\n")
    mtime = _time.time() - 7200
    os.utime(wt, (mtime, mtime))

    down_calls: list[set[str]] = []
    monkeypatch.setattr(_dc_mod, "down_run", lambda slugs: down_calls.append(set(slugs)) or 1)
    monkeypatch.setattr(orch._utils, "emit_event", lambda *a, **k: None)

    orch._batch._prune_stale_containers()

    assert down_calls, "devcontainer.down_run must be called even when dirty worktrees exist"


# ── _chunk_timeout: non-integer env + config fall through to default ─────────


def test_chunk_timeout_bad_env_falls_through_to_config(monkeypatch):
    """Non-integer MENTAT_CHUNK_TIMEOUT is ignored; config value wins."""
    orch = load_module("orchestrate")
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "not-a-number")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": 900})
    assert orch._supervise._chunk_timeout() == 900


def test_chunk_timeout_bad_config_falls_through_to_default(monkeypatch):
    """Non-integer config chunk_timeout falls back to the 1800s default."""
    orch = load_module("orchestrate")
    monkeypatch.delenv("MENTAT_CHUNK_TIMEOUT", raising=False)
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"chunk_timeout": "lots"})
    assert orch._supervise._chunk_timeout() == 1800


# ── _kill_proc_group: process-group resolution + SIGKILL ─────────────────────


def test_kill_proc_group_signals_the_group(monkeypatch):
    """With a resolvable pgid, _kill_proc_group killpg's the whole group."""
    orch = load_module("orchestrate")

    class _P:
        pid = 4242

    monkeypatch.setattr(orch._supervise.os, "getpgid", lambda _pid: 4242)
    killpg_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(orch._supervise.os, "killpg", lambda pgid, sig: killpg_calls.append((pgid, sig)))

    orch._supervise._kill_proc_group(_P())

    assert killpg_calls == [(4242, orch._supervise.signal.SIGKILL)]


def test_kill_proc_group_falls_back_when_no_pid(monkeypatch):
    """A proc without a real pid falls back to proc.kill() (no killpg)."""
    orch = load_module("orchestrate")

    killed = {"n": 0}

    class _P:
        pid = None

        def kill(self):
            killed["n"] += 1

    monkeypatch.setattr(
        orch._supervise.os, "killpg", lambda *a: (_ for _ in ()).throw(AssertionError("must not killpg"))
    )

    orch._supervise._kill_proc_group(_P())
    assert killed["n"] == 1


# ── supervisor throttle: cap<N with a hung early chunk frees a slot ──────────


def test_fan_out_plans_hung_chunk_frees_slot_for_queued(monkeypatch, tmp_path):
    """cap=1 + a hung first chunk: the semaphore only frees once the hung chunk
    is killed at its deadline, so the queued chunk still runs to completion."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plans = [routing.Plan(slug=f"h{i}", kind="AFK", blocked_by=[], path=tmp_path / f"h{i}.md") for i in range(2)]

    monkeypatch.setattr(orch._supervise, "_chunk_timeout", lambda: 0.05)
    monkeypatch.setattr(orch._supervise, "_concurrency_cap", lambda: 1)
    procs = [FakeAsyncProc(hang=True), FakeAsyncProc(sleep=0.01, rc=0)]
    monkeypatch.setattr(orch._supervise._spawn, "spawn_async", _async_spawner(procs, tmp_path))

    results = orch._batch._fan_out_plans(plans, harness=None, model=None)

    rc_by = {p.slug: rc for p, rc, *_ in results}
    assert rc_by["h0"] is not None and rc_by["h0"] < 0, f"hung h0 must be killed: {rc_by}"
    assert rc_by["h1"] == 0, f"h1 must run once h0's slot frees: {rc_by}"
