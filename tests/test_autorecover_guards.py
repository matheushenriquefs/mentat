"""Tests for mentat-autorecover-guards — supervisor guardrails S1-S4.

S1: concurrency backpressure — cap clamps to cpu_count//2, clamp logged.
S2: no-progress watchdog — a live-but-stalled chunk is killed before the wall.
S3: circuit breaker — N consecutive rc69 open the breaker; probe re-closes it.
S4: signal-clean shutdown + capped backoff-with-jitter helper.
"""

from __future__ import annotations

from pathlib import Path

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
