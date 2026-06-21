"""F5: checkpoint + respawn — crosses threshold → writes summary → seeds next spawn.

Red tracers:
- _compaction_threshold() returns int from config or None
- _invoke_harness passes seed_summary from MENTAT_SEED_SUMMARY env
- _checkpoint_if_needed writes summary.md{status:succeeded} when threshold crossed
- fan_out._spawn_worktree_subprocess injects MENTAT_SEED_SUMMARY when prior run crossed threshold
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
IMPL_SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"
FAN_OUT_SCRIPT = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/fan_out.py"
sys.path.insert(0, str(REPO_ROOT / ".agents"))


def _impl():
    return load_script(IMPL_SCRIPTS / "implement.py", "impl_f5")


def _fan_out():
    return load_script(FAN_OUT_SCRIPT, "fan_out_f5")


# ── _compaction_threshold ─────────────────────────────────────────────────────


def test_compaction_threshold_returns_none_when_no_config(tmp_path: Path) -> None:
    """F5 tracer: _compaction_threshold returns None when config absent."""
    impl = _impl()
    with patch.dict("os.environ", {"MENTAT_CONFIG": str(tmp_path / "absent.toml")}):
        result = impl._compaction_threshold()
    assert result is None


def test_compaction_threshold_reads_from_config(tmp_path: Path) -> None:
    """F5 tracer: _compaction_threshold reads compaction_threshold_tokens from config.toml."""
    impl = _impl()
    cfg = tmp_path / "config.toml"
    cfg.write_text("compaction_threshold_tokens = 50000\n")
    with patch.dict("os.environ", {"MENTAT_CONFIG": str(cfg)}):
        result = impl._compaction_threshold()
    assert result == 50000


# ── seed_summary forwarded to invoke() ───────────────────────────────────────


def test_invoke_harness_passes_seed_summary_from_env(tmp_path: Path) -> None:
    """F5 tracer: _invoke_harness passes seed_summary=MENTAT_SEED_SUMMARY to adapter."""
    impl = _impl()

    captured: list[dict] = []

    class FakeAdapter:
        def invoke(self, prompt, *, afk, model, seed_summary=None):
            captured.append({"seed_summary": seed_summary})
            return MagicMock(returncode=0, usage_tokens=None, session_log=None)

    fake_mod = FakeAdapter()

    def fake_load(key, path):
        return fake_mod

    with (
        patch.object(impl, "_load_mod", fake_load),
        patch.dict("os.environ", {"MENTAT_SEED_SUMMARY": "prior session context"}),
    ):
        impl._invoke_harness("claude-code", "do it", afk=False, model=None)

    assert captured, "_invoke_harness did not call adapter"
    assert captured[0]["seed_summary"] == "prior session context", (
        f"seed_summary not forwarded: {captured[0]['seed_summary']!r}"
    )


# ── _checkpoint_if_needed ─────────────────────────────────────────────────────


def test_checkpoint_if_needed_writes_summary_when_threshold_crossed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5 tracer: threshold crossed → summary.md written with status: succeeded."""
    impl = _impl()
    monkeypatch.setenv("MENTAT_SESSION", "test-session-f5")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")

    result_mock = MagicMock()
    result_mock.usage_tokens = 200000

    impl._checkpoint_if_needed(result_mock, slug="myplan", threshold=100000)

    from lib.session import summary_file

    path = summary_file("test-session-f5")
    assert path.exists(), "summary.md not written after threshold crossed"
    text = path.read_text()
    assert "status: succeeded" in text or "status:succeeded" in text.replace(" ", ""), (
        f"summary.md missing status:succeeded — got:\n{text}"
    )


def test_checkpoint_if_needed_noop_below_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 tracer: usage below threshold → no summary written."""
    impl = _impl()
    monkeypatch.setenv("MENTAT_SESSION", "test-session-f5-below")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")

    result_mock = MagicMock()
    result_mock.usage_tokens = 10000

    impl._checkpoint_if_needed(result_mock, slug="myplan", threshold=100000)

    from lib.session import summary_file

    path = summary_file("test-session-f5-below")
    assert not path.exists(), "summary.md written when below threshold — should be noop"


# ── fan_out._spawn_worktree_subprocess MENTAT_SEED_SUMMARY ───────────────────


def test_fan_out_spawn_injects_seed_summary_into_child_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 tracer: _spawn_worktree_subprocess must set MENTAT_SEED_SUMMARY in child env when provided."""
    fan_out = _fan_out()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")

    plan_path = tmp_path / "myplan.md"
    plan_path.write_text("---\nid: myplan\n---\nbody\n")

    captured_env: list[dict] = []

    class FakeProc:
        pass

    def fake_popen(cmd, env=None, **kwargs):
        captured_env.append(dict(env or {}))
        return FakeProc()

    with patch("subprocess.Popen", fake_popen):
        sid, proc = fan_out._spawn_worktree_subprocess(plan_path, seed_summary="prior summary text")

    assert captured_env, "Popen was not called"
    assert "MENTAT_SEED_SUMMARY" in captured_env[0], "MENTAT_SEED_SUMMARY not injected into child env"
    assert captured_env[0]["MENTAT_SEED_SUMMARY"] == "prior summary text"


def test_fan_out_spawn_no_seed_summary_absent_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 tracer: _spawn_worktree_subprocess must NOT set MENTAT_SEED_SUMMARY when seed_summary is None."""
    fan_out = _fan_out()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    monkeypatch.delenv("MENTAT_SEED_SUMMARY", raising=False)

    plan_path = tmp_path / "myplan.md"
    plan_path.write_text("---\nid: myplan\n---\nbody\n")

    captured_env: list[dict] = []

    class FakeProc:
        pass

    def fake_popen(cmd, env=None, **kwargs):
        captured_env.append(dict(env or {}))
        return FakeProc()

    with patch("subprocess.Popen", fake_popen):
        sid, proc = fan_out._spawn_worktree_subprocess(plan_path, seed_summary=None)

    assert captured_env, "Popen was not called"
    assert "MENTAT_SEED_SUMMARY" not in captured_env[0], (
        "MENTAT_SEED_SUMMARY unexpectedly present in child env when seed_summary=None"
    )


# ── orchestrate._fan_out_plans between-chunk seed forwarding ──────────────────

ORCH_SCRIPT = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/orchestrate.py"


def _orchestrate():
    return load_script(ORCH_SCRIPT, "orch_f5")


def test_fan_out_plans_seeds_next_chunk_from_completed_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """F5 tracer: _fan_out_plans passes seed_summary from completed chunk's summary.md to next spawn."""
    orch = _orchestrate()
    scheduler = load_script(REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/scheduler.py", "sched_f5")

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")

    plan_a_path = tmp_path / "plan-a.md"
    plan_a_path.write_text("---\nid: plan-a\nclass: AFK\nblocked_by: []\n---\nbody\n")
    plan_b_path = tmp_path / "plan-b.md"
    plan_b_path.write_text("---\nid: plan-b\nclass: AFK\nblocked_by: []\n---\nbody\n")

    plans = [
        scheduler.Plan(slug="plan-a", class_="AFK", blocked_by=[], path=plan_a_path),
        scheduler.Plan(slug="plan-b", class_="AFK", blocked_by=[], path=plan_b_path),
    ]

    spawn_calls: list[dict] = []
    session_counter = [0]

    class FakeProc:
        returncode = 0

        def __init__(self):
            self._done = False

        def poll(self):
            return 0 if self._done else None

        def wait(self):
            self._done = True

    def fake_spawn_with_proc(plan, *, harness=None, model=None, seed_summary=None):
        session_counter[0] += 1
        sid = f"implement-{plan.slug}-{session_counter[0]}"
        spawn_calls.append({"slug": plan.slug, "seed_summary": seed_summary, "session_id": sid})
        proc = FakeProc()
        proc._done = True
        return sid, proc

    # Write a summary file for plan-a's session after plan-a "completes"
    # We must know the session_id ahead of time to pre-write the file — use the first sid
    first_sid = "implement-plan-a-1"
    from lib.session import summary_file

    sf = summary_file(first_sid)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text("---\nstatus: succeeded\n---\nCheckpoint summary from plan-a.\n")

    with patch.object(orch._fan_out, "spawn_with_proc", fake_spawn_with_proc):
        orch._fan_out_plans(plans, harness=None, model=None)

    assert len(spawn_calls) == 2, f"Expected 2 spawns, got {len(spawn_calls)}"
    assert spawn_calls[0]["slug"] == "plan-a"
    assert spawn_calls[0]["seed_summary"] is None, "First chunk must not have a seed_summary"
    assert spawn_calls[1]["slug"] == "plan-b"
    assert spawn_calls[1]["seed_summary"] is not None, "Second chunk must receive seed_summary from plan-a's summary"
    assert "plan-a" in spawn_calls[1]["seed_summary"] or "succeeded" in spawn_calls[1]["seed_summary"]
