"""Tests for mentat-orchestrate supervise module (concurrency cap, fan-out throttle)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import bind_plan, load_script

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


# ── concurrency cap (ADR-0004) ──────────────────────────────────────────────


class _CountingAsyncProc:
    """asyncio.subprocess.Process double that tracks peak concurrency.

    On spawn it bumps a shared live-counter; communicate() yields to the loop a
    few times (so siblings interleave) then exits 0, decrementing the counter.
    """

    def __init__(self, live: dict, watermark: dict) -> None:
        self.pid = None
        self.returncode: int | None = None
        self._live = live
        self._watermark = watermark

    async def communicate(self):
        import asyncio as _a

        self._live["n"] += 1
        self._watermark["n"] = max(self._watermark["n"], self._live["n"])
        for _ in range(3):
            await _a.sleep(0)
        self._live["n"] -= 1
        self.returncode = 0
        return (b"", b"")

    async def wait(self):
        return self.returncode


def test_concurrency_cap_defaults_to_3_when_config_missing(monkeypatch):
    supervise = load_module("supervise")
    monkeypatch.setattr(supervise._utils, "read_config", lambda: {})
    monkeypatch.setattr(supervise.os, "cpu_count", lambda: 32)  # headroom well above the default
    assert supervise._concurrency_cap() == 3


def test_concurrency_cap_reads_config(monkeypatch):
    supervise = load_module("supervise")
    monkeypatch.setattr(supervise._utils, "read_config", lambda: {"concurrency": 7})
    monkeypatch.setattr(supervise.os, "cpu_count", lambda: 32)  # headroom above config → no clamp
    assert supervise._concurrency_cap() == 7


def test_concurrency_cap_clamps_to_min_1(monkeypatch):
    supervise = load_module("supervise")
    monkeypatch.setattr(supervise.os, "cpu_count", lambda: 32)
    monkeypatch.setattr(supervise._utils, "read_config", lambda: {"concurrency": 0})
    assert supervise._concurrency_cap() == 1
    monkeypatch.setattr(supervise._utils, "read_config", lambda: {"concurrency": -5})
    assert supervise._concurrency_cap() == 1


def test_concurrency_cap_rejects_bad_value(monkeypatch):
    supervise = load_module("supervise")
    monkeypatch.setattr(supervise._utils, "read_config", lambda: {"concurrency": "lots"})
    monkeypatch.setattr(supervise.os, "cpu_count", lambda: 32)
    assert supervise._concurrency_cap() == 3


def test_fan_out_plans_blocks_until_slot_free(monkeypatch, tmp_path):
    """With cap=2 and 4 plans, the asyncio semaphore must keep at most 2 chunks
    running concurrently — the peak live count never exceeds the cap."""
    supervise = load_module("supervise")
    routing = load_module("scheduler")

    monkeypatch.setattr(supervise, "_concurrency_cap", lambda: 2)
    monkeypatch.setattr(supervise, "_chunk_timeout", lambda: 5.0)

    plans = [routing.Plan(slug=f"p{i}", kind="AFK", blocked_by=[], path=tmp_path / f"p{i}.md") for i in range(4)]
    for i in range(4):
        bind_plan(f"p{i}")

    live = {"n": 0}
    high_watermark = {"n": 0}

    async def fake_spawn(plan, *, harness=None, model=None, seed_summary=None):
        return (f"sess-{plan.slug}", _CountingAsyncProc(live, high_watermark), tmp_path / plan.slug)

    monkeypatch.setattr(supervise._spawn, "spawn_async", fake_spawn)

    results = supervise._fan_out_plans(plans, harness=None, model=None)
    assert [p.slug for p, *_ in results] == ["p0", "p1", "p2", "p3"]
    assert all(rc == 0 for _p, rc, *_ in results)
    assert high_watermark["n"] <= 2, f"cap=2 was breached; saw {high_watermark['n']} concurrent live subprocesses"
