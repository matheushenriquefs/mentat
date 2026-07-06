"""drain tears down container after every chunk exit path."""

from __future__ import annotations

from pathlib import Path

import landing
import scheduler
from lib import devcontainer as _dc_mod  # noqa: E402

from tests.conftest import TEST_CHUNK_ID


def _plan(slug: str, blocked_by: list[str] | None = None) -> scheduler.Plan:
    return scheduler.Plan(
        slug=slug,
        kind="AFK",
        blocked_by=blocked_by or [],
        path=Path(f"/tmp/{slug}.md"),
    )


def _chunk(slug: str, tmp_path: Path) -> landing.Chunk:
    wt = tmp_path / ".mentat" / "worktrees" / TEST_CHUNK_ID / slug
    wt.mkdir(parents=True, exist_ok=True)
    return landing.Chunk(slug=slug, worktree=wt, chunk_id=TEST_CHUNK_ID)


def _install_stubs(
    monkeypatch,
    *,
    rebase_fail: set[str] | None = None,
    gate_block: set[str] | None = None,
    ff_fail: set[str] | None = None,
    torn_down: list[str],
) -> None:
    def fake_rebase(chunk, holding):
        if rebase_fail and chunk.slug in rebase_fail:
            return (None, "conflict")
        return (f"sha-{chunk.slug}", None)

    def fake_gates(chunk):
        if gate_block and chunk.slug in gate_block:
            return ("block", "stub-block")
        return ("pass", "")

    def fake_ff(chunk, holding):
        if ff_fail and chunk.slug in ff_fail:
            return "not_ff"
        return None

    def fake_teardown(chunk: landing.Chunk) -> None:
        torn_down.append(chunk.slug)

    monkeypatch.setattr(landing, "_rebase_chunk", fake_rebase)
    monkeypatch.setattr(landing, "_run_gates", fake_gates)
    monkeypatch.setattr(landing, "_ff_merge", fake_ff)
    monkeypatch.setattr(landing, "_emit_event", lambda *a, **kw: None)
    monkeypatch.setattr(landing, "_teardown_container", fake_teardown)


def test_drain_tears_down_after_success(tmp_path, monkeypatch) -> None:
    torn_down: list[str] = []
    _install_stubs(monkeypatch, torn_down=torn_down)
    chunk = _chunk("ok", tmp_path)

    results = landing.drain([chunk], holding="holding")

    assert results[0]["status"] == "success"
    assert "ok" in torn_down, f"container not torn down after success; torn_down={torn_down}"


def test_drain_tears_down_after_rebase_eject(tmp_path, monkeypatch) -> None:
    torn_down: list[str] = []
    _install_stubs(monkeypatch, rebase_fail={"conflict-slug"}, torn_down=torn_down)
    chunk = _chunk("conflict-slug", tmp_path)

    results = landing.drain([chunk], holding="holding")

    assert results[0]["status"] == "eject"
    assert results[0]["reason"] == "rebase_conflicted"
    assert "conflict-slug" in torn_down


def test_drain_tears_down_after_gate_eject(tmp_path, monkeypatch) -> None:
    torn_down: list[str] = []
    _install_stubs(monkeypatch, gate_block={"blocked-slug"}, torn_down=torn_down)
    chunk = _chunk("blocked-slug", tmp_path)

    results = landing.drain([chunk], holding="holding")

    assert results[0]["status"] == "eject"
    assert results[0]["reason"] == "gate_failed"
    assert "blocked-slug" in torn_down


def test_drain_tears_down_after_not_ff(tmp_path, monkeypatch) -> None:
    torn_down: list[str] = []
    _install_stubs(monkeypatch, ff_fail={"noff-slug"}, torn_down=torn_down)
    chunk = _chunk("noff-slug", tmp_path)

    results = landing.drain([chunk], holding="holding")

    assert results[0]["status"] == "eject"
    assert results[0]["reason"] == "not_ff"
    assert "noff-slug" in torn_down


def test_drain_tears_down_cascaded_eject(tmp_path, monkeypatch) -> None:
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])
    torn_down: list[str] = []
    _install_stubs(monkeypatch, gate_block={"a"}, torn_down=torn_down)

    chunks = [_chunk("a", tmp_path), _chunk("b", tmp_path)]
    landing.drain(
        chunks,
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    assert "a" in torn_down, f"ejected chunk a not torn down; torn_down={torn_down}"
    assert "b" in torn_down, f"cascaded chunk b not torn down; torn_down={torn_down}"


def test_teardown_failure_swallowed(tmp_path, monkeypatch) -> None:
    """subprocess returning non-zero: drain continues, chunk_teardown emitted with ok=false."""
    emitted: list[tuple[str, dict]] = []

    import subprocess as _sp

    def fake_run(cmd, **kw):
        class _R:
            returncode = 1
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(landing, "_rebase_chunk", lambda c, h: (f"sha-{c.slug}", None))
    monkeypatch.setattr(landing, "_run_gates", lambda c: ("pass", ""))
    monkeypatch.setattr(landing, "_ff_merge", lambda c, h: None)
    monkeypatch.setattr(landing, "_emit_event", lambda e, p: emitted.append((e, p)))
    monkeypatch.setattr(landing._utils, "read_config", lambda: {})
    monkeypatch.setattr(_sp, "run", fake_run)

    chunk = _chunk("fail-slug", tmp_path)
    results = landing.drain([chunk], holding="holding")

    assert results[0]["status"] == "success", "drain must complete despite teardown failure"
    teardown_events = [p for e, p in emitted if e == "chunk_teardown"]
    assert teardown_events, "chunk_teardown event must be emitted"
    assert teardown_events[0]["ok"] is False


def test_teardown_delegates_to_devcontainer_down(monkeypatch):
    down_calls: list[str] = []
    monkeypatch.setattr(_dc_mod, "down", lambda slug, **kw: down_calls.append(slug) or True)
    monkeypatch.setattr(landing, "_emit_event", lambda *a, **kw: None)

    landing._teardown_container(landing.Chunk(slug="my-chunk", worktree=Path("/tmp/my-chunk"), chunk_id=TEST_CHUNK_ID))

    assert down_calls == [f"{TEST_CHUNK_ID}/my-chunk"]


def test_drain_tears_down_all_pending_on_stall(tmp_path, monkeypatch) -> None:
    """Stalled drain must tear down containers for all pending chunks, not just landed ones."""
    a, b = _plan("a"), _plan("b", blocked_by=["a"])
    sched = scheduler.Scheduler([a, b])
    torn_down: list[str] = []
    _install_stubs(monkeypatch, torn_down=torn_down)

    # Only b's chunk arrives — a never does → stall; b's container must be torn down
    chunks = [_chunk("b", tmp_path)]
    results = landing.drain(
        chunks,
        holding="holding",
        on_landed=sched.mark_landed,
        on_ejected=sched.mark_ejected,
        list_ready_slices=sched.list_ready_slices,
    )

    stalled = [r for r in results if r.get("status") == "stalled"]
    assert stalled, f"expected stalled verdict, got {results}"
    assert "b" in torn_down, f"stalled chunk b container must be torn down; torn_down={torn_down}"
