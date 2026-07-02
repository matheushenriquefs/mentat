"""B1: worker-died eject reason — signal/abnormal child exit detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


# ── EJECT_REASONS catalog ──────────────────────────────────────────────────────


def test_worker_died_in_eject_reasons():
    from lib.events import EJECT_REASONS, EjectReason

    assert EjectReason.WORKER_DIED in EJECT_REASONS
    assert EjectReason.WORKER_DIED == "worker-died"


# ── _partition_fanout: signal exit ejects not lands ───────────────────────────


def _run_partition(orch, routing, tmp_path, rc):
    plan = routing.Plan(slug="dead-chunk", class_="AFK", blocked_by=[], path=tmp_path / "dead-chunk.md")
    emitted = []
    with patch.object(orch, "_emit_event", side_effect=lambda ev, p: emitted.append((ev, p))):
        with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
            sched = routing.Scheduler([plan])
            chunks, hitl, _transient = orch._partition_fanout([(plan, rc)], mark_ejected=sched.mark_ejected)
    return chunks, hitl, emitted


def test_signal_exit_negative_rc_ejects_as_worker_died(tmp_path):
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.events import EjectReason

    chunks, hitl, emitted = _run_partition(orch, routing, tmp_path, -9)

    assert chunks == [], "dead worker must not enter land queue"
    assert hitl == set(), "worker-died is not a HITL chunk"
    assert any(ev == "chunk.ejected" and p.get("reason") == EjectReason.WORKER_DIED for ev, p in emitted), (
        f"worker-died eject not emitted; got {emitted}"
    )


def test_shell_signal_exit_128_plus_ejects_as_worker_died(tmp_path):
    """rc=137 (128+SIGKILL) from a shell-wrapped subprocess."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.events import EjectReason

    chunks, hitl, emitted = _run_partition(orch, routing, tmp_path, 137)

    assert chunks == [], "dead worker must not enter land queue"
    assert any(ev == "chunk.ejected" and p.get("reason") == EjectReason.WORKER_DIED for ev, p in emitted), (
        f"worker-died eject not emitted for rc=137; got {emitted}"
    )


def test_worker_died_boundary_rc_128_ejects(tmp_path):
    """rc=128 itself also triggers worker-died (boundary)."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.events import EjectReason

    chunks, hitl, emitted = _run_partition(orch, routing, tmp_path, 128)

    assert chunks == [], "rc=128 must not enter land queue"
    assert any(ev == "chunk.ejected" and p.get("reason") == EjectReason.WORKER_DIED for ev, p in emitted), (
        f"worker-died not emitted for rc=128; got {emitted}"
    )


def test_normal_nonzero_rc_ejects_as_implement_failed(tmp_path):
    """rc=1 (implement-failed) must eject, not land (Slice 1 fix)."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.events import EjectReason

    chunks, hitl, emitted = _run_partition(orch, routing, tmp_path, 1)

    assert chunks == [], "rc=1 must not reach land queue"
    assert hitl == set()
    assert any(ev == "chunk.ejected" and p.get("reason") == EjectReason.IMPLEMENT_FAILED for ev, p in emitted), (
        f"implement-failed not emitted for rc=1; got {emitted}"
    )


def test_hitl_rc_still_routes_to_hitl(tmp_path):
    """EX_HITL_REQUIRED (42) is not a signal — must remain hitl-required path."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    from lib.events import EjectReason
    from lib.exits import EX_HITL_REQUIRED

    chunks, hitl, emitted = _run_partition(orch, routing, tmp_path, EX_HITL_REQUIRED)

    assert chunks == [], "HITL chunk must not land"
    assert "dead-chunk" in hitl
    assert any(ev == "chunk.ejected" and p.get("reason") == EjectReason.HITL_REQUIRED for ev, p in emitted), (
        f"hitl-required eject not emitted; got {emitted}"
    )
