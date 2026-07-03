"""S3: optional speculative-parallel land (bors batch / Zuul speculative).

Behind a config flag (``speculative_land``, default off), the land queue gates a
whole independent batch *concurrently* — assuming every chunk lands — then
FF-merges serially. Any gate or merge failure abandons the optimistic path and
falls back to a clean serial re-drain so ejects land with their real reasons.

Serial stays the safe default; speculation only cuts the O(N) gate latency for
large independent batches.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def make_chunk(slug: str):
    lq = load_module("land_queue")
    return lq.Chunk(slug=slug, worktree=Path(f"/tmp/{slug}"))


# ── flag default: OFF → serial ────────────────────────────────────────────────


def test_speculative_disabled_by_default_reads_config_false():
    """`speculative_land` absent from config → helper returns False (serial path)."""
    lq = load_module("land_queue")
    with patch.object(lq._utils, "read_config", return_value={}):
        assert lq._speculative_land_enabled() is False


def test_speculative_enabled_when_config_true():
    lq = load_module("land_queue")
    with patch.object(lq._utils, "read_config", return_value={"speculative_land": True}):
        assert lq._speculative_land_enabled() is True


def test_drain_default_off_uses_serial_path():
    """With the flag off, drain lands chunks serially (one land() call each, in order)."""
    lq = load_module("land_queue")
    chunks = [make_chunk(f"c{i}") for i in range(3)]
    call_order: list[str] = []

    def fake_land(chunk, *, holding):
        call_order.append(chunk.slug)
        return {"status": "success", "tip": "abc", "slug": chunk.slug}

    with (
        patch.object(lq, "land", side_effect=fake_land),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_speculative_land_enabled", return_value=False),
    ):
        results = lq.drain(chunks, holding="main")

    assert call_order == ["c0", "c1", "c2"]
    assert [r["status"] for r in results] == ["success"] * 3


# ── speculative ON: parallel gate, all land ───────────────────────────────────


def test_speculative_gates_run_in_parallel_and_all_land():
    """N independent chunks, flag on → gates run concurrently, whole batch lands.

    A threading.Barrier(N) proves concurrency: every gate must arrive at the
    barrier before any is released. A serial gate loop would deadlock and the
    barrier's timeout would raise, failing the test.
    """
    lq = load_module("land_queue")
    chunks = [make_chunk(f"c{i}") for i in range(3)]
    barrier = threading.Barrier(3, timeout=5)
    gated: list[str] = []

    def fake_gate(chunk):
        barrier.wait()  # raises BrokenBarrierError on timeout if run serially
        gated.append(chunk.slug)
        return ("pass", "")

    with (
        patch.object(lq, "_concurrency_cap", return_value=3),  # cap >= batch → true parallel
        patch.object(lq, "_rebase_chunk", return_value=("sha", None)),
        patch.object(lq, "_run_gates", side_effect=fake_gate),
        patch.object(lq, "_ff_merge", return_value=None),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        results = lq.drain(chunks, holding="main", speculative=True)

    assert sorted(gated) == ["c0", "c1", "c2"], "all chunks gated in the parallel wave"
    assert [r["status"] for r in results] == ["success"] * 3
    assert all(r["tip"] == "sha" for r in results)


def test_speculative_emits_landed_for_each_chunk():
    lq = load_module("land_queue")
    chunks = [make_chunk("a"), make_chunk("b")]

    with (
        patch.object(lq, "_rebase_chunk", return_value=("sha", None)),
        patch.object(lq, "_run_gates", return_value=("pass", "")),
        patch.object(lq, "_ff_merge", return_value=None),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event") as mock_emit,
    ):
        lq.drain(chunks, holding="main", speculative=True)

    landed = [c.args[1]["slug"] for c in mock_emit.call_args_list if c.args[0] == "chunk.landed"]
    assert sorted(landed) == ["a", "b"]


# ── speculative gate threadpool is bounded by the concurrency cap ──────────────


def _run_speculative_capturing_workers(lq, chunks):
    """Drain a batch speculatively, returning the max_workers the gate threadpool
    was created with."""
    captured: dict = {}
    real_tpe = lq.concurrent.futures.ThreadPoolExecutor

    def spy_tpe(*a, max_workers=None, **k):
        captured["max_workers"] = max_workers
        return real_tpe(*a, max_workers=max_workers, **k)

    with (
        patch.object(lq.concurrent.futures, "ThreadPoolExecutor", spy_tpe),
        patch.object(lq, "_rebase_chunk", return_value=("sha", None)),
        patch.object(lq, "_run_gates", return_value=("pass", "")),
        patch.object(lq, "_ff_merge", return_value=None),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        lq.drain(chunks, holding="main", speculative=True)
    return captured["max_workers"]


def test_speculative_threadpool_bounded_by_cap():
    """A batch larger than the cap must not spawn one thread per chunk — the gate
    threadpool is bounded by the effective concurrency cap (C < N → C workers)."""
    lq = load_module("land_queue")
    chunks = [make_chunk(f"c{i}") for i in range(8)]
    with patch.object(lq, "_concurrency_cap", return_value=3):
        workers = _run_speculative_capturing_workers(lq, chunks)
    assert workers == 3, f"max_workers must be bounded by cap (3), got {workers}"


def test_speculative_threadpool_never_exceeds_chunk_count():
    """When the cap exceeds the batch size, the pool is sized to the batch — never
    over-allocated idle threads."""
    lq = load_module("land_queue")
    chunks = [make_chunk("a"), make_chunk("b")]
    with patch.object(lq, "_concurrency_cap", return_value=16):
        workers = _run_speculative_capturing_workers(lq, chunks)
    assert workers == 2, f"max_workers must not exceed chunk count (2), got {workers}"


def test_land_concurrency_cap_clamps_to_half_cores(monkeypatch):
    """The land-queue cap mirrors the fan-out clamp: config 8 on a 4-core box → 2."""
    lq = load_module("land_queue")
    monkeypatch.setattr(lq._utils, "read_config", lambda: {"concurrency": 8})
    monkeypatch.setattr(lq.os, "cpu_count", lambda: 4)
    assert lq._concurrency_cap() == 2


# ── speculative ON: mid-batch failure → serial fallback with correct ejects ───


def test_speculative_gate_failure_falls_back_to_serial_drain():
    """One chunk red under speculation → fall back to serial; correct per-chunk ejects.

    Fallback re-drains the whole batch through land(): the failing chunk ejects
    with its real reason (gate-failed), the others land clean.
    """
    lq = load_module("land_queue")
    chunks = [make_chunk("a"), make_chunk("b"), make_chunk("c")]

    def fake_gates(chunk):
        return ("block", "b is smelly") if chunk.slug == "b" else ("pass", "")

    with (
        patch.object(lq, "_rebase_chunk", return_value=("sha", None)),
        patch.object(lq, "_run_gates", side_effect=fake_gates),
        patch.object(lq, "_ff_merge", return_value=None),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        results = lq.drain(chunks, holding="main", speculative=True)

    by_slug = {r["slug"]: r for r in results}
    assert by_slug["a"]["status"] == "success"
    assert by_slug["c"]["status"] == "success"
    assert by_slug["b"]["status"] == "eject"
    assert by_slug["b"]["reason"] == "gate-failed"


def test_speculative_merge_conflict_falls_back_to_serial():
    """All gates green but a merge collides with the advancing tip → serial fallback.

    Chunk `a` lands, `b`'s FF-merge reports not-ff → fall back to serial re-drain
    of the remainder. `b` ejects not-ff, `c` still lands.
    """
    lq = load_module("land_queue")
    chunks = [make_chunk("a"), make_chunk("b"), make_chunk("c")]

    def fake_ff(chunk, holding):
        return "not-ff" if chunk.slug == "b" else None

    with (
        patch.object(lq, "_rebase_chunk", return_value=("sha", None)),
        patch.object(lq, "_run_gates", return_value=("pass", "")),
        patch.object(lq, "_ff_merge", side_effect=fake_ff),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        results = lq.drain(chunks, holding="main", speculative=True)

    by_slug = {r["slug"]: r for r in results}
    assert by_slug["a"]["status"] == "success"
    assert by_slug["b"]["status"] == "eject"
    assert by_slug["b"]["reason"] == "not-ff"
    assert by_slug["c"]["status"] == "success"


def test_speculative_only_applies_to_independent_path():
    """With a dep-aware next_ready, drain stays serial even if speculative is on.

    Speculation assumes 1..N-1 land; a live dep graph forbids that, so the
    dep-aware path is left on the safe serial rebase.
    """
    lq = load_module("land_queue")
    chunks = [make_chunk("a"), make_chunk("b")]
    land_calls: list[str] = []

    def fake_land(chunk, *, holding):
        land_calls.append(chunk.slug)
        return {"slug": chunk.slug, "status": "success", "tip": "x"}

    def fake_next_ready(pending):
        return pending[0] if pending else None

    with (
        patch.object(lq, "land", side_effect=fake_land),
        patch.object(lq, "_teardown_container", lambda _s: None),
        patch.object(lq, "_emit_event", lambda *a, **k: None),
    ):
        results = lq.drain(chunks, holding="main", speculative=True, next_ready=fake_next_ready)

    # land() invoked per chunk = serial dep-aware path, not the speculative wave.
    assert land_calls == ["a", "b"]
    assert [r["status"] for r in results] == ["success", "success"]
