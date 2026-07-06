"""E2E: the fan-out supervisor's *throttle-wait* reaper + the failing-run summary.

The per-chunk-deadline tests (``test_orchestrate_per_chunk_deadline``) drive 1-2
plans, so they never fill the concurrency cap and never exercise the reaper that
fires *while a spawn waits for a free slot*. That throttle-wait reaper is the real
AFK-contention path: N plans, cap C < N, a hung early chunk must be group-killed to
free a slot for the queued ones — otherwise the whole batch stalls behind it (the
"orchestrate kept timing out" symptom). These tests pin ``concurrency = 1`` so the
second plan always waits, driving both the healthy-drain and the kill-to-free-a-slot
branches with real subprocesses.

The final test drives ``run_orchestrate``'s non-dry failing path end-to-end
(anchored emit + stalled report + cascade-eject to an anchored victim + the named
eject summary) with the spawn/land seams stubbed.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"

# A child that sleeps argv[1] seconds then exits argv[2].
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
    """spawn_async fake launching a real child per slug: slug -> (sleep_s, exit)."""
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
    return scheduler.Plan(slug=slug, kind="AFK", blocked_by=[], path=Path(f"/tmp/{slug}.md"))


def _pin_cap_one(monkeypatch, orch) -> None:
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 1})


# ── throttle-wait reaper ──────────────────────────────────────────────────────


def test_throttle_wait_drains_healthy_chunk_before_spawning_next(monkeypatch, tmp_path):
    """cap=1: B waits while A runs. A finishes under its deadline, so the
    throttle loop reaps nothing (checks-but-not-overdue), harvests A's seed, then
    spawns B. Both return their true exit codes."""
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    _pin_cap_one(monkeypatch, orch)
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "10")
    monkeypatch.setattr(
        orch._supervise._spawn,
        "spawn_async",
        _spawner(tmp_path, {"a": (0.4, 0), "b": (0.1, 0)}),
    )

    results = orch._supervise._fan_out_plans([_plan(scheduler, "a"), _plan(scheduler, "b")], harness=None, model=None)

    by_slug = {item[0].slug: item[1] for item in results}
    assert by_slug == {"a": 0, "b": 0}


def test_throttle_wait_kills_hung_chunk_to_free_a_slot(monkeypatch, tmp_path):
    """cap=1 + a hung A: B cannot spawn until a slot frees. The throttle-wait
    reaper group-kills the overdue A (past MENTAT_CHUNK_TIMEOUT) so B runs. This
    is the multi-chunk AFK-contention timeout the operator hit — a hung early
    chunk must not wedge the whole queue."""
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    _pin_cap_one(monkeypatch, orch)
    monkeypatch.setenv("MENTAT_CHUNK_TIMEOUT", "1")
    monkeypatch.setattr(
        orch._supervise._spawn,
        "spawn_async",
        _spawner(tmp_path, {"a": (30.0, 0), "b": (0.3, 0)}),
    )

    started = time.monotonic()
    results = orch._supervise._fan_out_plans([_plan(scheduler, "a"), _plan(scheduler, "b")], harness=None, model=None)
    elapsed = time.monotonic() - started

    by_slug = {plan.slug: rc for plan, rc, *_ in results}
    assert by_slug["a"] is not None and by_slug["a"] < 0, f"hung A must be killed (rc<0), got {by_slug['a']}"
    assert by_slug["b"] == 0, f"B must run once A's slot frees, got {by_slug['b']}"
    # A was reaped ~1s in, not left to run its full 30s sleep.
    assert elapsed < 15, f"queue should not block on A's full sleep (took {elapsed:.1f}s)"


# ── run_orchestrate non-dry failing path ──────────────────────────────────────


def test_run_orchestrate_failing_batch_reports_stall_cascade_and_ejects(monkeypatch, tmp_path):
    """Full non-dry run where an auto chunk fails and cascades to an anchored
    downstream: exercises the anchored emit, the stalled report, the
    anchored-cascade upstream_ejected emit, and the named eject summary."""
    orch = load_module("orchestrate")
    scheduler = load_module("scheduler")

    # A realistic cascade: `core` is genuinely auto (fanned out), and `ui` is
    # anchored via its OWN upstream HITL (`gate`), not by being downstream of
    # core — an auto chunk with a HITL *downstream* would itself be anchored by
    # the partition rule, so it would never fan out. When core's chunk fails,
    # mark_ejected cascades to the anchored ui (which also blocks on core).
    gate = scheduler.Plan(slug="gate", kind="HITL", blocked_by=[], path=tmp_path / "gate.md")
    core = scheduler.Plan(slug="core", kind="AFK", blocked_by=[], path=tmp_path / "core.md")
    ui = scheduler.Plan(slug="ui", kind="AFK", blocked_by=["core", "gate"], path=tmp_path / "ui.md")

    monkeypatch.setattr(orch, "ensure_session", lambda role, slug: "sess-x")
    monkeypatch.setattr(orch, "_load_plans", lambda paths: [gate, core, ui])
    monkeypatch.setattr(orch._batch, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orch._batch, "_prune_stale_worktrees", lambda *, preserve=None: None)
    monkeypatch.setattr(orch._batch, "_worktree_for_slug", lambda slug: tmp_path / slug)
    # Auto chunk fails (rc=1) → real partition_by_outcome ejects it + cascades to ui.
    monkeypatch.setattr(orch._batch, "_fan_out_plans", lambda auto, *, harness, model: [(core, 1)])
    # Land queue returns a stalled row + an eject row for the failed core chunk.
    drain_rows = [
        {"status": "stalled", "pending": ["core"]},
        {"status": "eject", "slug": "core", "reason": "gate_failed"},
    ]
    monkeypatch.setattr(orch._batch._land_queue, "drain", lambda *a, **k: drain_rows)

    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(orch, "_emit_event", lambda ev, p: emitted.append((ev, p)))
    monkeypatch.setattr(orch._batch, "_emit_event", lambda ev, p: emitted.append((ev, p)))
    monkeypatch.setattr(orch._utils, "emit_event", lambda ev, p: emitted.append((ev, p)))

    with patch.object(orch.sys, "stderr"):
        rc = orch.run_orchestrate("hold", [tmp_path / "batch.md"], harness=None, model=None, dry_run=False)

    assert rc == 1  # ejections present
    # Anchored chunk_started emitted for the HITL plan.
    spawned = [p for ev, p in emitted if ev == "chunk_started"]
    assert any(p.get("slug") == "ui" for p in spawned)
    # ui is an anchored cascade victim → upstream_ejected emitted for it.
    upstream = [p for ev, p in emitted if ev == "chunk_ejected" and p.get("reason") == "upstream_ejected"]
    assert any(p.get("slug") == "ui" for p in upstream)
    # Batch review still emitted (advisory).
    assert any(ev == "batch_reviewed" for ev, _p in emitted)
