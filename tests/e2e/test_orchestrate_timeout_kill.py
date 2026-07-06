"""E2E: timeout kill reaps the whole process group, not just the parent (Bug A).

fan_out spawns the implement child with ``start_new_session=True`` so the harness
grandchild inherits the child's process group. On a chunk timeout, orchestrate's
``_kill_proc_group`` group-kills that pgid with SIGKILL. This test proves the
grandchild — which ignores SIGTERM and would otherwise orphan and keep running —
is reaped by the group SIGKILL, and that the dead worker ejects ``worker-died``
with its worktree left in place.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


# A real child that forks a grandchild; both ignore SIGTERM and sleep. The
# grandchild pid is written to a file so the test can prove it was reaped.
# Neither process calls setsid — start_new_session on the Popen already makes
# the child the group leader, and the grandchild inherits the group via fork.
_CHILD_SRC = dedent(
    """
    import os, signal, sys, time
    pidfile = sys.argv[1]
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pid = os.fork()
    if pid == 0:
        # grandchild: ignore SIGTERM, advertise pid, then sleep
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(pidfile, "w") as f:
            f.write(str(os.getpid()))
        time.sleep(300)
        os._exit(0)
    # parent: also ignore SIGTERM so the kill must escalate to SIGKILL
    time.sleep(300)
    """
)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_timeout_group_kill_reaps_grandchild(monkeypatch, tmp_path):
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    child_script = tmp_path / "child.py"
    child_script.write_text(_CHILD_SRC)
    pidfile = tmp_path / "grandchild.pid"

    plan = scheduler.Plan(slug="hung", kind="AFK", blocked_by=[], path=tmp_path / "hung.md")

    async def fake_spawn(_plan, *, harness=None, model=None, seed_summary=None):
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(child_script),
            str(pidfile),
            start_new_session=True,
        )
        return "sess-hung", proc, tmp_path / "worktree"

    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "1")
    monkeypatch.setattr(orch._fan_out, "spawn_async", fake_spawn)

    results = orch._fan_out_plans([plan], harness=None, model=None)

    # Grandchild pid must have been written before the kill landed.
    deadline = time.monotonic() + 2.0
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pidfile.exists(), "grandchild never advertised its pid"
    grandchild_pid = int(pidfile.read_text().strip())

    # The whole group was SIGKILLed — the SIGTERM-ignoring grandchild is gone.
    for _ in range(40):
        if not _pid_alive(grandchild_pid):
            break
        time.sleep(0.1)
    assert not _pid_alive(grandchild_pid), f"grandchild {grandchild_pid} survived the group kill"

    # The dead worker returns a negative rc → partition ejects worker-died.
    assert len(results) == 1
    _plan, rc = results[0][0], results[0][1]
    assert rc is not None and rc < 0, f"killed worker must report a signal rc, got {rc}"

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    emitted: list[tuple[str, dict]] = []
    with patch.object(orch, "_worktree_for_slug", return_value=worktree):
        with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            chunks, hitl, _transient = orch.partition_by_outcome(results, mark_ejected=lambda _slug: [])

    assert chunks == [] and not hitl
    ejects = [p for ev, p in emitted if ev == "chunk_ejected"]
    assert ejects and ejects[0]["reason"] == "worker_died"
    assert worktree.exists(), "worktree must be preserved for the operator"
