"""Tests for mentat-autorecover-guards — supervisor guardrails S1-S4.

S1: concurrency backpressure — cap clamps to cpu_count//2, clamp logged.
S2: no-progress watchdog — a live-but-stalled chunk is killed before the wall.
S3: circuit breaker — N consecutive rc69 open the breaker; probe re-closes it.
S4: signal-clean shutdown + capped backoff-with-jitter helper.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _make_plan_obj(tmp_path: Path, slug: str, class_: str = "AFK"):
    routing = load_module("scheduler")
    p = tmp_path / f"{slug}.md"
    p.write_text(f"---\nid: {slug}\nclass: {class_}\n---\n")
    return routing.Plan(slug=slug, class_=class_, blocked_by=[], path=p)


# ── S2/S4 fakes (shared) ──────────────────────────────────────────────────────


class FakeAsyncProc:
    """asyncio.subprocess.Process double. pid=None → kill() fallback."""

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
        if self.returncode is None:
            self.returncode = -9


def _async_spawner(procs):
    it = iter(procs)

    async def spawn_async(plan, *, harness=None, model=None, seed_summary=None):
        return (f"sess-{plan.slug}", next(it))

    return spawn_async


# ── S1: concurrency backpressure clamp ────────────────────────────────────────


def test_concurrency_cap_clamps_to_half_cores(monkeypatch, capsys):
    """config concurrency=8 on a 4-CPU box → effective cap == 2; clamp logged."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 8})
    monkeypatch.setattr(orch.os, "cpu_count", lambda: 4)

    assert orch._concurrency_cap() == 2, "8 must clamp to cpu_count//2 == 2"
    err = capsys.readouterr().err
    assert "clamp" in err.lower(), f"clamp must be logged; got: {err!r}"
    assert "8" in err and "2" in err, f"log must name want→effective; got: {err!r}"


def test_concurrency_cap_no_clamp_when_config_fits(monkeypatch, capsys):
    """A config that fits under the headroom ceiling is returned verbatim, no log."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 3})
    monkeypatch.setattr(orch.os, "cpu_count", lambda: 16)

    assert orch._concurrency_cap() == 3
    assert "clamp" not in capsys.readouterr().err.lower()


def test_concurrency_cap_floors_at_1_on_single_core(monkeypatch):
    """A 1-CPU box floors the ceiling at 1 (never 0)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 8})
    monkeypatch.setattr(orch.os, "cpu_count", lambda: 1)
    assert orch._concurrency_cap() == 1


def test_concurrency_cap_handles_none_cpu_count(monkeypatch):
    """os.cpu_count() returning None degrades to a 1-core ceiling."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"concurrency": 8})
    monkeypatch.setattr(orch.os, "cpu_count", lambda: None)
    assert orch._concurrency_cap() == 1


def test_load_headroom_ok_permissive_when_getloadavg_missing(monkeypatch):
    """No getloadavg (unsupported platform) → permissive True."""
    orch = load_module("orchestrate")

    def _boom():
        raise AttributeError("no getloadavg")

    monkeypatch.setattr(orch.os, "getloadavg", _boom)
    assert orch._load_headroom_ok() is True


def test_load_headroom_ok_false_when_saturated(monkeypatch):
    """load-per-core >= 1.0 → not ok (advisory)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch.os, "getloadavg", lambda: (16.0, 0, 0))
    monkeypatch.setattr(orch.os, "cpu_count", lambda: 4)
    assert orch._load_headroom_ok() is False


def test_load_headroom_ok_true_when_idle(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch.os, "getloadavg", lambda: (0.5, 0, 0))
    monkeypatch.setattr(orch.os, "cpu_count", lambda: 4)
    assert orch._load_headroom_ok() is True


# ── S2: no-progress watchdog ──────────────────────────────────────────────────


def test_stall_timeout_default_is_300(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {})
    monkeypatch.delenv("MENTAT_STALL_TIMEOUT", raising=False)
    assert orch._stall_timeout() == 300


def test_stall_timeout_reads_config(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"stall_timeout": 120})
    monkeypatch.delenv("MENTAT_STALL_TIMEOUT", raising=False)
    assert orch._stall_timeout() == 120


def test_stall_timeout_env_overrides_config(monkeypatch):
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"stall_timeout": 120})
    monkeypatch.setenv("MENTAT_STALL_TIMEOUT", "30")
    assert orch._stall_timeout() == 30


def test_stall_timeout_zero_disables(monkeypatch):
    """A non-positive stall_timeout disables the watchdog (returns <=0)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"stall_timeout": 0})
    monkeypatch.delenv("MENTAT_STALL_TIMEOUT", raising=False)
    assert orch._stall_timeout() <= 0


def test_event_age_none_when_no_log(tmp_path, monkeypatch):
    """No session.jsonl → None (not a stall — a just-spawned chunk)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch, "_session_dir", lambda sid: tmp_path)
    assert orch._event_age("sess-x") is None


def test_event_age_reads_mtime(tmp_path, monkeypatch):
    """An existing log → a non-negative age from its mtime."""
    import os as _os
    import time as _time

    orch = load_module("orchestrate")
    log = tmp_path / "session.jsonl"
    log.write_text("{}\n")
    _os.utime(log, (_time.time() - 42, _time.time() - 42))
    monkeypatch.setattr(orch, "_session_dir", lambda sid: tmp_path)
    age = orch._event_age("sess-x")
    assert age is not None and age >= 40


def test_fan_out_plans_kills_stalled_chunk_before_wall(monkeypatch, tmp_path):
    """A live-but-silent chunk (no audit event for the stall window) is killed
    with reason 'stalled' while the wall clock still has budget."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="stalled", class_="AFK", blocked_by=[], path=tmp_path / "stalled.md")

    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 30.0)  # wall far away
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0.05)  # tiny stall window
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch, "_event_age", lambda sid: 999.0)  # log gone silent
    monkeypatch.setattr(orch._devcontainer, "down", lambda slug: True)
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(hang=True)]))

    results = orch._fan_out_plans([plan], harness=None, model=None)

    _p, rc, _logs, reason = results[0]
    assert rc is not None and rc < 0, f"stalled chunk must be killed (rc<0), got {rc}"
    assert reason == "stalled", f"kill reason must be 'stalled', got {reason!r}"


def test_fan_out_plans_progress_resets_stall_window(monkeypatch, tmp_path):
    """A chunk that keeps emitting events (age below the window) is NOT killed as
    stalled — it runs to its natural completion."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="live", class_="AFK", blocked_by=[], path=tmp_path / "live.md")

    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 30.0)
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0.05)
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch, "_event_age", lambda sid: 0.0)  # always fresh
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(sleep=0.15, rc=0)]))

    results = orch._fan_out_plans([plan], harness=None, model=None)

    _p, rc, _logs, reason = results[0]
    assert rc == 0, f"a live chunk must complete, got rc={rc}"
    assert reason is None, f"a live chunk must not be killed, got reason={reason!r}"


def test_partition_fanout_stalled_kill_names_killer(tmp_path):
    """A stalled kill (rc<0 + reason 'stalled') → payload killed_by:'stalled',
    reason worker-died, and it is transient (retryable)."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "st")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._devcontainer, "down", lambda slug: True):
            with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
                _c, _h, transient = orch._partition_fanout(
                    [(plan, -9, "/logs/st", "stalled")],
                    mark_ejected=lambda slug: [],
                )

    p = [p for ev, p in emitted if ev == "chunk.ejected"][0]
    assert p["reason"] == "worker-died"
    assert p["killed_by"] == "stalled"
    assert "timed_out" not in p, "a stall is not a wall timeout"
    assert "st" in transient
