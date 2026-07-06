"""E2E: each chunk owns an independent per-chunk deadline (Bug B).

The old serial wait phase blocked on chunk A's full deadline before looking at
chunk B, so by the time it reached B the shared wall-clock had run down and a
healthy B was killed with an instant TimeoutExpired. The supervisor loop measures
every child against its own spawn time, so a slow-but-healthy sibling never
shrinks another chunk's budget. These tests drive real subprocesses through
``_fan_out_plans`` to prove it.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"

# A child that sleeps `argv[1]` seconds then exits `argv[2]`.
_CHILD_SRC = dedent(
    """
    import sys, time
    time.sleep(float(sys.argv[1]))
    sys.exit(int(sys.argv[2]))
    """
)


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _spawner(tmp_path: Path, behavior: dict[str, tuple[float, int]]):
    """Return a spawn_async fake that launches a real child per plan slug.

    behavior maps slug -> (sleep_seconds, exit_code).
    """
    child_script = tmp_path / "child.py"
    child_script.write_text(_CHILD_SRC)

    async def fake_spawn(plan, *, harness=None, model=None, seed_summary=None):
        sleep_s, code = behavior[plan.slug]
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(child_script),
            str(sleep_s),
            str(code),
            start_new_session=True,
        )
        return f"sess-{plan.slug}", proc, tmp_path / plan.slug

    return fake_spawn


def _plan(scheduler, slug: str):
    return scheduler.Plan(slug=slug, class_="AFK", blocked_by=[], path=Path(f"/tmp/{slug}.md"))


def test_healthy_sibling_not_killed_by_slow_sibling(monkeypatch, tmp_path):
    """A long-but-under-deadline A must not shrink B's budget.

    Under the old serial wait, B's remaining budget = deadline - A_runtime
    (= 5 - 3.5 = 1.5s) < B's 2s sleep, so B was wrongly killed. Both must now
    return their true exit codes.
    """
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "5")
    monkeypatch.setattr(
        orch._fan_out,
        "spawn_async",
        _spawner(tmp_path, {"a": (3.5, 5), "b": (2.0, 0)}),
    )

    results = orch._fan_out_plans([_plan(scheduler, "a"), _plan(scheduler, "b")], harness=None, model=None)

    by_slug = {item[0].slug: item[1] for item in results}
    assert by_slug == {"a": 5, "b": 0}, f"both must return true exit codes, neither killed: {by_slug}"


def test_only_overdue_chunk_killed(monkeypatch, tmp_path):
    """A past its deadline is killed; a healthy B under deadline lands clean."""
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "2")
    monkeypatch.setattr(
        orch._fan_out,
        "spawn_async",
        _spawner(tmp_path, {"a": (30.0, 0), "b": (0.5, 0)}),
    )

    results = orch._fan_out_plans([_plan(scheduler, "a"), _plan(scheduler, "b")], harness=None, model=None)
    by_slug = {plan.slug: rc for plan, rc, *_ in results}
    assert by_slug["a"] is not None and by_slug["a"] < 0, f"overdue A must be killed (rc<0), got {by_slug['a']}"
    assert by_slug["b"] == 0, f"healthy B must exit 0, got {by_slug['b']}"

    # Partition routes the killed A to worker-died and keeps B landable.
    wt_a, wt_b = tmp_path / "wt-a", tmp_path / "wt-b"
    wt_a.mkdir()
    wt_b.mkdir()
    emitted: list[tuple[str, dict]] = []

    def fake_worktree(slug: str):
        return wt_a if slug == "a" else wt_b

    with patch.object(orch, "_worktree_for_slug", side_effect=fake_worktree):
        with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            chunks, hitl, _transient = orch._partition_fanout(results, mark_ejected=lambda _slug: [])

    assert not hitl
    assert [c.slug for c in chunks] == ["b"], "B must be the only landable chunk"
    a_ejects = [p for ev, p in emitted if ev == "chunk.ejected" and p["slug"] == "a"]
    assert a_ejects and a_ejects[0]["reason"] == "worker-died"
