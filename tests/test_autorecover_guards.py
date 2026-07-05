"""Tests for mentat-autorecover-guards — supervisor guardrails S1-S4.

S1: concurrency backpressure — cap clamps to cpu_count//2, clamp logged.
S2: no-progress watchdog — a live-but-stalled chunk is killed before the wall.
S3: circuit breaker — N consecutive rc69 open the breaker; probe re-closes it.
S4: signal-clean shutdown + capped backoff-with-jitter helper.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import async_spawner, load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"
LIB = Path(__file__).resolve().parents[1] / ".agents/lib"


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


def _async_spawner(procs, worktree: Path):
    return async_spawner(procs, worktree)


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
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(hang=True)], tmp_path))

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
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(sleep=0.15, rc=0)], tmp_path))

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


# ── S3: circuit breaker on shared deps ────────────────────────────────────────


def test_breaker_opens_after_threshold_consecutive_failures():
    """N consecutive failures OPEN the breaker; further allow() short-circuits."""
    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=3, cooldown_s=1000.0)  # long cooldown → stays open
    assert b.allow() is True
    b.record_failure()
    b.record_failure()
    assert b.state != "open", "must not open before the threshold"
    b.record_failure()
    assert b.state == "open", "threshold reached → open"
    assert b.allow() is False, "open breaker must short-circuit (no spawn)"
    assert b.allow() is False, "still short-circuits while cooling down"


def test_breaker_success_resets_consecutive_count():
    """A success between failures resets the count — non-consecutive failures never trip."""
    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=3, cooldown_s=1000.0)
    b.record_failure()
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.state == "closed", "count reset by success → not open"


def test_breaker_half_open_probe_closes_on_success():
    """After cooldown the breaker half-opens, admits ONE probe; success re-CLOSEs."""
    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=2, cooldown_s=0.0)  # cooldown elapsed immediately
    b.record_failure()
    b.record_failure()
    assert b.state == "open"
    assert b.allow() is True, "cooldown elapsed → admit one probe"
    assert b.allow() is False, "the in-flight probe blocks siblings"
    b.record_success()
    assert b.state == "closed"
    assert b.allow() is True


def test_breaker_probe_failure_reopens():
    """A failed probe re-OPENs the breaker (backend still sick)."""
    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=1, cooldown_s=0.0)
    b.record_failure()
    assert b.state == "open"
    assert b.allow() is True  # probe
    b.record_failure()  # probe failed
    assert b.state == "open", "failed probe must re-open"


def test_breaker_half_open_admits_exactly_one_probe_under_concurrency():
    """N concurrent tasks calling allow() in the half-open window → exactly one is
    admitted, the rest short-circuit until the probe resolves. (allow() claims the
    single-probe token synchronously, so no await between allow and record can let a
    second probe slip through.)"""
    import asyncio

    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=1, cooldown_s=0.0)
    b.record_failure()  # open; cooldown 0 → first allow half-opens
    admits: list = []

    async def probe():
        ok = b.allow()
        admits.append(ok)
        await asyncio.sleep(0)  # yield between allow and (never) record

    async def main():
        await asyncio.gather(*[probe() for _ in range(5)])

    asyncio.run(main())
    assert sum(1 for a in admits if a) == 1, f"exactly one probe may be admitted: {admits}"


def test_breaker_abandoned_probe_releases_and_recools():
    """A probe that ends WITHOUT a backend verdict (our own deadline killed it) must
    release the single-probe token and return to cooling — not wedge the breaker
    half-open forever, short-circuiting the whole remaining fleet."""
    orch = load_module("orchestrate")
    clk = [0.0]
    b = orch._CircuitBreaker(threshold=1, cooldown_s=5.0, clock=lambda: clk[0])
    b.record_failure()  # open at t=0
    clk[0] = 5.0
    assert b.allow() is True, "cooldown elapsed → one probe"
    assert b.allow() is False, "sibling short-circuits while the probe is in flight"
    b.record_abandoned()  # probe killed by our deadline — no backend verdict
    assert b._probe_inflight is False, "abandon must release the probe token"
    assert b.allow() is False, "still cooling immediately after abandon"
    clk[0] = 10.0
    assert b.allow() is True, "an abandoned probe must not wedge the breaker"


def test_breaker_abandoned_noop_when_closed():
    """record_abandoned on a healthy (closed) breaker is a no-op — a non-probe kill
    doesn't perturb a backend that's up."""
    orch = load_module("orchestrate")
    b = orch._CircuitBreaker(threshold=3, cooldown_s=1000.0)
    b.record_abandoned()
    assert b.state == "closed" and b.allow() is True


def test_supervisor_releases_probe_on_kill(monkeypatch, tmp_path):
    """A half-open probe chunk killed by our own deadline (rc<0) must release the
    breaker's probe token via record_abandoned — otherwise the token wedges and every
    queued chunk short-circuits 'breaker-open' forever."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="p", class_="AFK", blocked_by=[], path=tmp_path / "p.md")

    clk = [100.0]
    b = orch._CircuitBreaker(threshold=1, cooldown_s=0.0, clock=lambda: clk[0])
    b.record_failure()  # open; cooldown 0 → the run's allow() half-opens (probe)
    monkeypatch.setattr(orch, "_make_breaker", lambda: b)
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 30.0)  # wall far away
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0.05)  # tiny stall window
    monkeypatch.setattr(orch, "_event_age", lambda sid: 999.0)  # force a stall kill
    monkeypatch.setattr(orch._devcontainer, "down", lambda slug: True)
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(hang=True)], tmp_path))

    orch._fan_out_plans([plan], harness=None, model=None)

    assert b._probe_inflight is False, "a killed probe must release the half-open token"
    assert b.allow() is True, "breaker must re-admit a probe, not stay wedged"


def test_supervisor_short_circuits_when_breaker_open(monkeypatch, tmp_path):
    """An open breaker → the chunk is NOT launched (spawn_async never called) and
    is ejected as a retryable 'breaker-open' transient."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="sc", class_="AFK", blocked_by=[], path=tmp_path / "sc.md")

    opened = orch._CircuitBreaker(threshold=1, cooldown_s=1000.0)
    opened.record_failure()  # now open, cooldown far off
    monkeypatch.setattr(orch, "_make_breaker", lambda: opened)
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)

    launches: list[str] = []

    async def spy_spawn(plan, *, harness=None, model=None, seed_summary=None):
        launches.append(plan.slug)
        return (f"sess-{plan.slug}", FakeAsyncProc(rc=0), tmp_path)

    monkeypatch.setattr(orch._fan_out, "spawn_async", spy_spawn)

    results = orch._fan_out_plans([plan], harness=None, model=None)

    assert launches == [], f"open breaker must not launch a spawn: {launches}"
    _p, rc, _logs, reason = results[0]
    assert rc == orch.EX_UNAVAILABLE, f"short-circuit must report EX_UNAVAILABLE, got {rc}"
    assert reason == "breaker-open"


def test_supervisor_records_rc69_as_breaker_failure(monkeypatch, tmp_path):
    """A live spawn returning rc69 feeds the breaker a failure; enough of them open it."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plans = [routing.Plan(slug=f"c{i}", class_="AFK", blocked_by=[], path=tmp_path / f"c{i}.md") for i in range(2)]

    b = orch._CircuitBreaker(threshold=2, cooldown_s=1000.0)
    monkeypatch.setattr(orch, "_make_breaker", lambda: b)
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)  # sequential → consecutive
    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 5.0)
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0)  # disable stall watchdog
    monkeypatch.setattr(orch._devcontainer, "down", lambda slug: True)
    monkeypatch.setattr(
        orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(rc=69), FakeAsyncProc(rc=69)], tmp_path)
    )

    orch._fan_out_plans(plans, harness=None, model=None)

    assert b.state == "open", "two consecutive rc69 spawns must open the breaker"


def test_partition_fanout_breaker_open_names_killer(tmp_path):
    """A breaker short-circuit (rc69 + reason 'breaker-open') → killed_by:'breaker-open'."""
    orch = load_module("orchestrate")
    plan = _make_plan_obj(tmp_path, "bo")
    emitted: list[tuple] = []

    with patch.object(orch, "_worktree_for_slug", return_value=tmp_path):
        with patch.object(orch._devcontainer, "down", lambda slug: True):
            with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
                _c, _h, transient = orch._partition_fanout(
                    [(plan, orch.EX_UNAVAILABLE, None, "breaker-open")],
                    mark_ejected=lambda slug: [],
                )

    p = [p for ev, p in emitted if ev == "chunk.ejected"][0]
    assert p["killed_by"] == "breaker-open"
    assert "bo" in transient


# ── S4: signal-clean shutdown + capped backoff-with-jitter helper ─────────────


class _KillTrackingProc:
    """A child proc double that records kill() calls (pid=None → kill() path)."""

    pid = None

    def __init__(self) -> None:
        self.killed = 0

    def kill(self) -> None:
        self.killed += 1


def test_group_teardown_kills_downs_and_emits_for_every_child():
    """_group_teardown group-kills each live child, stops its container, emits
    chunk.teardown, and clears the registry (no double teardown)."""
    from tests.conftest import TEST_CHUNK_ID, bind_plan, chunk_label

    orch = load_module("orchestrate")
    bind_plan("c0", TEST_CHUNK_ID)
    bind_plan("c1", TEST_CHUNK_ID)
    p0, p1 = _KillTrackingProc(), _KillTrackingProc()
    live = {"c0": p0, "c1": p1}
    down: list[str] = []
    emitted: list[tuple] = []

    with patch.object(orch._devcontainer, "down", lambda slug: down.append(slug) or True):
        with patch.object(orch, "_emit_event", lambda ev, p: emitted.append((ev, p))):
            orch._group_teardown(live)

    assert p0.killed == 1 and p1.killed == 1, "every child's group must be killed"
    assert set(down) == {chunk_label("c0"), chunk_label("c1")}, f"every child's container must be downed: {down}"
    teardowns = [p["slug"] for ev, p in emitted if ev == "chunk.teardown"]
    assert set(teardowns) == {"c0", "c1"}, f"chunk.teardown per child: {teardowns}"
    assert live == {}, "registry must be cleared so a re-entrant signal won't re-tear-down"


def test_install_signal_handlers_registers_sigint_and_sigterm():
    """Both SIGINT and SIGTERM are wired on the loop to the teardown handler."""
    orch = load_module("orchestrate")
    registered: list = []

    class _FakeLoop:
        def add_signal_handler(self, sig, cb, *args):
            registered.append(sig)

    orch._install_signal_handlers(_FakeLoop(), lambda name: None)

    assert orch.signal.SIGINT in registered
    assert orch.signal.SIGTERM in registered


def test_supervisor_installs_signal_handlers(monkeypatch, tmp_path):
    """_supervise_fanout wires the signal handlers on its running loop (so a
    SIGTERM tears the fleet down) — verified via a spy on _install_signal_handlers."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="s", class_="AFK", blocked_by=[], path=tmp_path / "s.md")

    captured: dict = {}

    def spy_install(loop, handler):
        captured["handler"] = handler

    monkeypatch.setattr(orch, "_install_signal_handlers", spy_install)
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 5.0)
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0)
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(rc=0)], tmp_path))

    orch._fan_out_plans([plan], harness=None, model=None)

    assert callable(captured.get("handler")), "supervisor must install a signal handler"


def test_install_signal_handlers_swallows_unsupported():
    """A loop that can't add signal handlers (off-main-thread) is tolerated."""
    orch = load_module("orchestrate")

    class _BadLoop:
        def add_signal_handler(self, *a):
            raise NotImplementedError

    orch._install_signal_handlers(_BadLoop(), lambda name: None)  # must not raise


# ── config fallbacks: malformed values degrade to defaults ────────────────────


def test_stall_timeout_bad_env_falls_through_to_config(monkeypatch):
    """A non-integer MENTAT_STALL_TIMEOUT is ignored; config wins (orchestrate.py 208-209)."""
    orch = load_module("orchestrate")
    monkeypatch.setenv("MENTAT_STALL_TIMEOUT", "not-an-int")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"stall_timeout": 42})
    assert orch._stall_timeout() == 42


def test_stall_timeout_bad_config_falls_back_to_300(monkeypatch):
    """A non-numeric config stall_timeout degrades to the 300 default (orchestrate.py 213-214)."""
    orch = load_module("orchestrate")
    monkeypatch.delenv("MENTAT_STALL_TIMEOUT", raising=False)
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"stall_timeout": "soon"})
    assert orch._stall_timeout() == 300


def test_breaker_threshold_bad_config_falls_back_to_3(monkeypatch):
    """A non-numeric breaker_threshold degrades to 3 (orchestrate.py 286-287)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"breaker_threshold": "many"})
    assert orch._breaker_threshold() == 3


def test_breaker_cooldown_bad_config_falls_back_to_30(monkeypatch):
    """A non-numeric breaker_cooldown degrades to 30.0 (orchestrate.py 295-296)."""
    orch = load_module("orchestrate")
    monkeypatch.setattr(orch._utils, "read_config", lambda: {"breaker_cooldown": "later"})
    assert orch._breaker_cooldown() == 30.0


# ── _kill_proc_group: getpgid failure fallback ────────────────────────────────


def test_kill_proc_group_falls_back_to_kill_when_getpgid_fails(monkeypatch):
    """A proc whose pid has no resolvable process group (already reaped) falls back
    to proc.kill() instead of raising (orchestrate.py 340-343)."""
    orch = load_module("orchestrate")
    killed: list[bool] = []

    class _Proc:
        pid = 4242

        def kill(self) -> None:
            killed.append(True)

    def _boom(_pid):
        raise ProcessLookupError()

    monkeypatch.setattr(orch.os, "getpgid", _boom)
    orch._kill_proc_group(_Proc())
    assert killed == [True]


# ── supervisor: low-headroom warning + signal teardown harvest ────────────────


def test_supervisor_warns_when_load_high_but_still_spawns(monkeypatch, tmp_path, capsys):
    """High host load is advisory — the chunk still spawns, with a warning
    (orchestrate.py branch 489->490, line 490)."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="hl", class_="AFK", blocked_by=[], path=tmp_path / "hl.md")

    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    monkeypatch.setattr(orch, "_chunk_timeout", lambda: 5.0)
    monkeypatch.setattr(orch, "_stall_timeout", lambda: 0)
    monkeypatch.setattr(orch, "_load_headroom_ok", lambda: False)

    launches: list[str] = []

    async def spy_spawn(plan, *, harness=None, model=None, seed_summary=None):
        launches.append(plan.slug)
        return (f"sess-{plan.slug}", FakeAsyncProc(rc=0), tmp_path)

    monkeypatch.setattr(orch._fan_out, "spawn_async", spy_spawn)

    results = orch._fan_out_plans([plan], harness=None, model=None)

    assert launches == ["hl"], "high load is advisory — chunk still spawns"
    assert "load high" in capsys.readouterr().err.lower()
    assert results[0][1] == 0


def test_supervisor_signal_handler_tears_down_and_cancels(monkeypatch, tmp_path):
    """The installed signal handler group-tears-down the live fleet and cancels
    every task; a cancelled task is harvested as a dead worker via the
    BaseException branch (orchestrate.py 519-526, 535)."""
    orch = load_module("orchestrate")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="sig", class_="AFK", blocked_by=[], path=tmp_path / "sig.md")

    teardowns: list = []
    monkeypatch.setattr(orch, "_group_teardown", lambda live: teardowns.append(dict(live)))
    monkeypatch.setattr(orch, "_concurrency_cap", lambda: 1)
    # Fire the handler synchronously at install time — before any task has run — so
    # every task is cancelled and harvested through the BaseException branch.
    monkeypatch.setattr(orch, "_install_signal_handlers", lambda loop, cb: cb("SIGTERM"))
    monkeypatch.setattr(orch._fan_out, "spawn_async", _async_spawner([FakeAsyncProc(rc=0)], tmp_path))

    results = orch._fan_out_plans([plan], harness=None, model=None)

    assert teardowns, "_group_teardown must run on signal"
    assert results[0][1] == -1, "a cancelled task is harvested as a dead worker (rc=-1)"


# ── S4: full-jitter backoff helper ────────────────────────────────────────────


def load_backoff():
    return load_script(LIB / "backoff.py", "backoff")


def test_full_jitter_never_exceeds_cap():
    backoff = load_backoff()
    # rng() at its max (→1.0) still must stay under the cap.
    for attempt in range(0, 20):
        delay = backoff.full_jitter(attempt, base=0.5, cap=10.0, rng=lambda: 0.9999)
        assert 0.0 <= delay <= 10.0, f"attempt {attempt} exceeded cap: {delay}"


def test_full_jitter_jitters_successive_calls():
    """Two calls at the same attempt differ — the whole point of jitter."""
    backoff = load_backoff()
    a = backoff.full_jitter(5, base=0.5, cap=30.0)
    b = backoff.full_jitter(5, base=0.5, cap=30.0)
    assert a != b, f"successive jittered delays must differ: {a} == {b}"


def test_full_jitter_ceiling_grows_with_attempt():
    """Higher attempt → higher ceiling (until capped). With rng fixed at 1.0 the
    returned delay equals the ceiling, so it is monotonic then flat at cap."""
    backoff = load_backoff()
    d0 = backoff.full_jitter(0, base=1.0, cap=100.0, rng=lambda: 1.0)
    d1 = backoff.full_jitter(1, base=1.0, cap=100.0, rng=lambda: 1.0)
    d2 = backoff.full_jitter(2, base=1.0, cap=100.0, rng=lambda: 1.0)
    assert d0 < d1 < d2, f"ceiling must grow: {d0}, {d1}, {d2}"


def test_full_jitter_negative_attempt_floored():
    backoff = load_backoff()
    delay = backoff.full_jitter(-3, base=1.0, cap=100.0, rng=lambda: 1.0)
    assert delay == 1.0, f"negative attempt must floor to 0 (ceiling=base): {delay}"
