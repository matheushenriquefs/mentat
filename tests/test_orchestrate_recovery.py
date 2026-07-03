"""S2: orchestrate's recovery wiring — the real spawn / land / re-plan primitives
bound into ``recover.recover``, plus the end-of-batch doctor + projection wiring.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ORCH_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ORCH_SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _plan(orch, slug, class_="AFK"):
    return orch._scheduler.Plan(slug=slug, class_=class_, blocked_by=[], path=Path(f"/tmp/{slug}.md"))


# ── _recovery_diff ────────────────────────────────────────────────────────────


def test_recovery_diff_returns_stdout(monkeypatch, tmp_path):
    orch = _load("orchestrate")

    class _R:
        returncode = 0
        stdout = "x" * 5000

    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: _R())
    out = orch._recovery_diff(tmp_path, "hold")
    assert len(out) == 4000  # truncated


def test_recovery_diff_empty_on_git_error(monkeypatch, tmp_path):
    orch = _load("orchestrate")

    class _R:
        returncode = 1
        stdout = "boom"

    monkeypatch.setattr(orch.subprocess, "run", lambda *a, **k: _R())
    assert orch._recovery_diff(tmp_path, "hold") == ""


def test_recovery_diff_empty_on_oserror(monkeypatch, tmp_path):
    orch = _load("orchestrate")

    def _boom(*a, **k):
        raise OSError

    monkeypatch.setattr(orch.subprocess, "run", _boom)
    assert orch._recovery_diff(tmp_path, "hold") == ""


# ── _recovery_context ─────────────────────────────────────────────────────────


def test_recovery_context_reads_summary(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "summary.md").write_text("what went wrong")
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: wt)
    monkeypatch.setattr(orch, "_recovery_diff", lambda w, h: "the-diff")
    ctx = orch._recovery_context(_plan(orch, "core"), 1, 2, holding="hold")
    assert ctx["diagnosis"] == "what went wrong"
    assert ctx["diff"] == "the-diff"
    assert ctx["attempt"] == 1 and ctx["cap"] == 2 and ctx["slug"] == "core"


def test_recovery_context_no_summary(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: wt)
    monkeypatch.setattr(orch, "_recovery_diff", lambda w, h: "")
    ctx = orch._recovery_context(_plan(orch, "core"), 1, 2, holding="hold")
    assert ctx["diagnosis"] == ""


# ── _spawn_implement_in_worktree ──────────────────────────────────────────────


def test_spawn_implement_in_worktree_reuses_worktree(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    captured = {}

    class _P:
        def wait(self):
            return 0

    def fake_popen(cmd, *, cwd=None, env=None, start_new_session=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["skip"] = env.get("MENTAT_SKIP_PREFLIGHT")
        return _P()

    monkeypatch.setattr(orch.subprocess, "Popen", fake_popen)
    rc = orch._spawn_implement_in_worktree(Path("/tmp/core.md"), tmp_path, harness="claude-code", model="m")
    assert rc == 0
    assert captured["skip"] == "1"  # idempotent reuse, no `worktree create`
    assert captured["cwd"] == str(tmp_path)
    assert "--harness" in captured["cmd"] and "--model" in captured["cmd"]


# ── _recovery_respawn ─────────────────────────────────────────────────────────


def test_recovery_respawn_lands_on_success(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: tmp_path)
    monkeypatch.setattr(orch._git, "discard_path", lambda *a, **k: None)
    monkeypatch.setattr(orch._git, "rebase_ff_only", lambda *a, **k: (None, None))
    monkeypatch.setattr(orch, "_spawn_implement_in_worktree", lambda *a, **k: 0)
    monkeypatch.setattr(orch._land_queue, "drain", lambda chunks, *, holding: [{"slug": "core", "status": "success"}])
    out = orch._recovery_respawn(_plan(orch, "core"), 1, holding="hold", harness=None, model=None)
    assert out == [{"slug": "core", "status": "success"}]


def test_recovery_respawn_ejects_on_implement_failure(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: tmp_path)
    monkeypatch.setattr(orch._git, "discard_path", lambda *a, **k: None)
    monkeypatch.setattr(orch._git, "rebase_ff_only", lambda *a, **k: (None, None))
    monkeypatch.setattr(orch, "_spawn_implement_in_worktree", lambda *a, **k: 1)
    monkeypatch.setattr(orch, "_emit_event", lambda *a, **k: None)
    out = orch._recovery_respawn(_plan(orch, "core"), 1, holding="hold", harness=None, model=None)
    assert out[0]["status"] == "eject" and out[0]["reason"] == "implement-failed"


# ── _reslice_agent + _recovery_reslice ────────────────────────────────────────


def test_reslice_agent_returns_written_slices(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    plan_path = tmp_path / "core.md"
    plan_path.write_text("big plan")

    def fake_invoke(prompt):
        (tmp_path / "core-r1.md").write_text("---\nid: core-r1\nclass: AFK\n---\n")
        (tmp_path / "core-r2.md").write_text("---\nid: core-r2\nclass: AFK\n---\n")
        return "done"

    monkeypatch.setattr(orch._recover, "_invoke_claude", fake_invoke)
    out = orch._reslice_agent(_plan_at(orch, "core", plan_path))
    assert [p.name for p in out] == ["core-r1.md", "core-r2.md"]


def test_recovery_reslice_empty_ejects(monkeypatch):
    orch = _load("orchestrate")
    monkeypatch.setattr(orch, "_reslice_agent", lambda plan: [])
    out = orch._recovery_reslice(_plan(orch, "core"), 1, holding="hold", harness=None, model=None)
    assert out[0]["status"] == "eject" and out[0]["note"] == "reslice-empty"


def test_recovery_reslice_fans_sub_slices(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    r1 = tmp_path / "core-r1.md"
    r1.write_text("---\nid: core-r1\nclass: AFK\nblocked_by: []\n---\n")
    monkeypatch.setattr(orch, "_reslice_agent", lambda plan: [r1])
    captured = {}

    def fake_run_batch(sub_plans, **kw):
        captured["slugs"] = [p.slug for p in sub_plans]
        return ([{"slug": "core-r1", "status": "success"}], set(), set())

    monkeypatch.setattr(orch, "_run_batch", fake_run_batch)
    out = orch._recovery_reslice(_plan(orch, "core"), 1, holding="hold", harness=None, model=None)
    assert captured["slugs"] == ["core-r1"]
    assert out[0]["status"] == "success"


# ── _recovery_backoff ─────────────────────────────────────────────────────────


def test_recovery_backoff_sleeps_the_full_jitter_delay(monkeypatch):
    """The injected backoff must SLEEP the computed full-jitter delay — the earlier
    wiring computed the delay then discarded it, so respawn spacing was a no-op."""
    orch = _load("orchestrate")
    monkeypatch.setattr(orch._backoff, "full_jitter", lambda i: 4.0 + i)
    slept: list = []
    orch._recovery_backoff(0, sleep=slept.append)
    orch._recovery_backoff(1, sleep=slept.append)
    assert slept == [4.0, 5.0], f"must sleep the jittered delay, not zero/skipped: {slept}"


def test_recovery_pass_spaces_respawns_with_jittered_sleep(monkeypatch, tmp_path):
    """A recovery pass with >=2 respawns invokes the sleep once per respawn with the
    full-jitter delay (asserted via a fake sleep spy) — not zero, not skipped."""
    orch = _load("orchestrate")
    recover = _load("recover")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setattr(recover, "_emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orch._backoff, "full_jitter", lambda i: 2.0 + i)
    slept: list = []
    monkeypatch.setattr(orch.time, "sleep", lambda d: slept.append(d))

    plans = {s: _plan(orch, s) for s in ("a", "b")}
    recover.recover(
        {"a", "b"},
        plans_by_slug=plans,
        holding="hold",
        session_id="s1",
        harness=None,
        is_afk=lambda s: True,
        context_builder=lambda p, a, c: {"slug": p.slug, "worktree": "w"},
        teardown=lambda s: None,
        respawn=lambda p, a: [{"slug": p.slug, "status": "success"}],
        reslice=lambda p, a: [],
        dead_letter=lambda p, r: None,
        decide=lambda ctx: {"action": "retry"},
        backoff=orch._recovery_backoff,
        cap=5,
    )
    assert slept == [2.0, 3.0], f"each respawn must sleep its jittered delay: {slept}"


# ── _run_recovery ─────────────────────────────────────────────────────────────


def test_run_recovery_retry_marks_recovered(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: tmp_path)
    monkeypatch.setattr(orch, "_teardown_ejected", lambda s: None)
    monkeypatch.setattr(orch, "_recovery_context", lambda p, a, c, *, holding: {"slug": p.slug, "worktree": "w"})
    monkeypatch.setattr(orch._recover, "decide", lambda ctx: {"action": "retry", "rationale": "env"})
    monkeypatch.setattr(orch, "_recovery_respawn", lambda p, a, **k: [{"slug": p.slug, "status": "success"}])
    monkeypatch.setattr(orch, "_emit_event", lambda *a, **k: None)
    plan = _plan(orch, "core")
    ok, dead = orch._run_recovery(
        {"core"}, plans_by_slug={"core": plan}, holding="hold", session_id="s1", harness=None, model=None
    )
    assert ok == {"core"} and dead == set()


def test_run_recovery_skipped_hitl_counts_neither(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    ui = _plan(orch, "ui", class_="HITL")
    ok, dead = orch._run_recovery(
        {"ui"}, plans_by_slug={"ui": ui}, holding="hold", session_id="s1", harness=None, model=None
    )
    assert ok == set() and dead == set()  # HITL is skipped, neither recovered nor dead-lettered


def test_run_orchestrate_invokes_recovery_for_worker_died(tmp_path, monkeypatch):
    """A worker-died auto chunk is marked transient in the wave and handed to recovery."""
    orch = _load("orchestrate")
    _load("scheduler")
    a = tmp_path / "a.md"
    a.write_text("---\nid: a\nstatus: ready\nclass: AFK\nblocked_by: []\n---\n# a\n")

    plan_obj = orch._scheduler.Plan(slug="a", class_="AFK", blocked_by=[], path=a)
    # rc<0 → worker-died → transient set.
    monkeypatch.setattr(orch, "_fan_out_plans", lambda plans, **kw: [(plan_obj, -1, str(tmp_path), None)])
    monkeypatch.setattr(orch._land_queue, "drain", lambda chunks, **kw: [])
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: tmp_path)
    monkeypatch.setattr(orch, "_teardown_ejected", lambda s: None)
    monkeypatch.setattr(orch, "_prune_stale_containers", lambda: None)
    monkeypatch.setattr(orch, "_prune_stale_worktrees", lambda **kw: None)
    monkeypatch.setattr(orch, "_gc_preserved_worktrees", lambda **kw: None)
    monkeypatch.setattr(orch, "_rebuild_projection", lambda: None)
    monkeypatch.setattr(orch, "_spawn_batch_doctor", lambda: None)
    monkeypatch.setattr(orch, "_emit_event", lambda *a, **k: None)
    monkeypatch.setattr(orch._utils, "emit_event", lambda *a, **k: None)

    captured = {}

    def fake_recovery(transient, **kw):
        captured["transient"] = set(transient)
        return set(), set()

    monkeypatch.setattr(orch, "_run_recovery", fake_recovery)
    orch.run_orchestrate("holding", [a], harness=None, model=None, dry_run=False)
    assert captured["transient"] == {"a"}


def test_run_recovery_abandon_dead_letters(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setattr(orch, "_worktree_for_slug", lambda s: tmp_path)
    monkeypatch.setattr(orch, "_teardown_ejected", lambda s: None)
    monkeypatch.setattr(orch, "_recovery_context", lambda p, a, c, *, holding: {"slug": p.slug})
    monkeypatch.setattr(orch._recover, "decide", lambda ctx: {"action": "abandon", "rationale": "no"})
    emitted = []
    monkeypatch.setattr(orch, "_emit_event", lambda ev, p: emitted.append((ev, p)))
    plan = _plan(orch, "core")
    ok, dead = orch._run_recovery(
        {"core"}, plans_by_slug={"core": plan}, holding="hold", session_id="s1", harness=None, model=None
    )
    assert ok == set() and dead == {"core"}
    assert any(ev == "chunk.ejected" and p["reason"] == "hitl-required" for ev, p in emitted)


# ── _rebuild_projection + _spawn_batch_doctor ─────────────────────────────────


def test_rebuild_projection_calls_state_rebuild(monkeypatch):
    orch = _load("orchestrate")
    from lib import state as state_mod

    calls = []
    monkeypatch.setattr(state_mod, "rebuild", lambda root, **k: calls.append(root) or {"projected": 0, "pruned": 0})
    orch._rebuild_projection()
    assert calls  # rebuild invoked


def test_spawn_batch_doctor_captures_to_session_dir(monkeypatch, tmp_path):
    orch = _load("orchestrate")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-doc")
    captured = {}

    class _P:
        pass

    def fake_popen(cmd, *, stdout=None, stderr=None):
        captured["cmd"] = cmd
        captured["stdout_named"] = getattr(stdout, "name", None)
        return _P()

    monkeypatch.setattr(orch.subprocess, "Popen", fake_popen)
    orch._spawn_batch_doctor()
    assert captured["cmd"][-1] == "sess-doc"  # session-scoped
    assert captured["stdout_named"] and captured["stdout_named"].endswith("doctor.out")


def _plan_at(orch, slug, path):
    return orch._scheduler.Plan(slug=slug, class_="AFK", blocked_by=[], path=path)
