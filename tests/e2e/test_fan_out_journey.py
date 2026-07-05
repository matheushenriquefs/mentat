"""E2E: the orchestrate fan-out spawner.

Drives ``fan_out.py`` by monkeypatching the single process seam
(``fan_out.subprocess.Popen``) with a recorder that captures the child cmd,
env, and ``start_new_session`` flag. No real subprocess is ever launched.
Log dirs are isolated by pointing ``MENTAT_LOG_PATH`` at a tmp dir and freezing
``MENTAT_REPO`` so the session dir arithmetic lands under tmp.
"""

from __future__ import annotations

import re
import types
from pathlib import Path

import pytest

from tests.conftest import fake_plan, load_script, mock_fan_out_worktree

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]

fan_out = load_script(REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/fan_out.py", "fan_out")


class FakePopen:
    """Stand-in for subprocess.Popen: records how it was constructed."""

    def __init__(self, cmd, *, env=None, start_new_session=False, **kwargs) -> None:
        self.cmd = cmd
        self.env = env
        self.start_new_session = start_new_session
        self.kwargs = kwargs


@pytest.fixture
def isolate_logs(monkeypatch, tmp_path):
    """Point the log root at tmp and freeze the repo name so session dirs land
    under tmp, and swap Popen for a capturing fake."""
    log_root = tmp_path / "logs"
    log_root.mkdir()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "fixrepo")
    captured: dict[str, FakePopen] = {}

    def fake_popen(cmd, **kwargs):
        proc = FakePopen(cmd, **kwargs)
        captured["proc"] = proc
        return proc

    monkeypatch.setattr(fan_out.subprocess, "Popen", fake_popen)
    worktree = tmp_path / "chunk-wt"
    worktree.mkdir()
    mock_fan_out_worktree(monkeypatch, fan_out, worktree)
    return types.SimpleNamespace(log_root=log_root, captured=captured, worktree=worktree)


def _plan_file(tmp_path: Path, name: str = "widget"):
    p = tmp_path / f"{name}.md"
    p.write_text("# plan\n")
    return fake_plan(p, name)


# ── _log_dir_for ──────────────────────────────────────────────────────────────


def test_log_dir_for_lands_under_tmp_log_root(isolate_logs):
    d = fan_out._log_dir_for("implement-widget-123")
    assert d == isolate_logs.log_root / "fixrepo" / "implement-widget-123"


# ── _spawn_worktree_subprocess ────────────────────────────────────────────────


def test_spawn_worktree_session_id_shape(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    session_id, _proc, _wt = fan_out._spawn_worktree_subprocess(plan)
    assert re.fullmatch(r"[0-9a-f]{32}", session_id), f"expected uuid session id, got {session_id!r}"


def test_spawn_worktree_creates_log_dir_0700(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    session_id, _proc, _wt = fan_out._spawn_worktree_subprocess(plan)
    log_dir = isolate_logs.log_root / "fixrepo" / session_id
    assert log_dir.exists()
    assert log_dir.stat().st_mode & 0o777 == 0o700


def test_spawn_worktree_cmd_is_bare_when_no_harness_or_model(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    fan_out._spawn_worktree_subprocess(plan)
    proc = isolate_logs.captured["proc"]
    assert proc.cmd == ["python3", str(fan_out._IMPLEMENT_SCRIPT), str(plan.path)]


def test_spawn_worktree_cmd_appends_harness_and_model(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    fan_out._spawn_worktree_subprocess(plan, harness="claude", model="opus")
    proc = isolate_logs.captured["proc"]
    assert proc.cmd == [
        "python3",
        str(fan_out._IMPLEMENT_SCRIPT),
        str(plan.path),
        "--harness",
        "claude",
        "--model",
        "opus",
    ]


def test_spawn_worktree_env_carries_session_and_log(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    session_id, _proc, _wt = fan_out._spawn_worktree_subprocess(plan)
    proc = isolate_logs.captured["proc"]
    assert proc.env["MENTAT_SESSION"] == session_id
    expected_log = isolate_logs.log_root / "fixrepo" / session_id / "session.jsonl"
    assert proc.env["MENTAT_SESSION_LOG"] == str(expected_log)


def test_spawn_worktree_omits_seed_summary_when_absent(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    fan_out._spawn_worktree_subprocess(plan)
    proc = isolate_logs.captured["proc"]
    assert "MENTAT_SEED_SUMMARY" not in proc.env


def test_spawn_worktree_includes_seed_summary_when_passed(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    fan_out._spawn_worktree_subprocess(plan, seed_summary="prior context")
    proc = isolate_logs.captured["proc"]
    assert proc.env["MENTAT_SEED_SUMMARY"] == "prior context"


def test_spawn_worktree_starts_new_session(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    fan_out._spawn_worktree_subprocess(plan)
    assert isolate_logs.captured["proc"].start_new_session is True


def test_spawn_worktree_returns_session_id_and_proc(isolate_logs, tmp_path):
    plan = _plan_file(tmp_path)
    session_id, proc, _wt = fan_out._spawn_worktree_subprocess(plan)
    assert isinstance(session_id, str)
    assert proc is isolate_logs.captured["proc"]


# ── spawn_with_proc ───────────────────────────────────────────────────────────


def _fake_plan(tmp_path: Path):
    p = tmp_path / "widget.md"
    p.write_text("# plan\n")
    return fake_plan(p, "s")


def test_spawn_with_proc_emits_chunk_spawned_default_harness(isolate_logs, tmp_path, monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(fan_out, "_emit_event", lambda name, payload: events.append((name, payload)))
    fan_out.spawn_with_proc(_fake_plan(tmp_path))
    assert events[0][0] == "chunk.spawned"
    assert events[0][1]["harness"] == "default"


def test_spawn_with_proc_emits_passed_harness(isolate_logs, tmp_path, monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(fan_out, "_emit_event", lambda name, payload: events.append((name, payload)))
    fan_out.spawn_with_proc(_fake_plan(tmp_path), harness="claude")
    assert events[0][1]["harness"] == "claude"


def test_spawn_with_proc_prints_track_command_and_session_id(isolate_logs, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fan_out, "_emit_event", lambda name, payload: None)
    session_id, _proc = fan_out.spawn_with_proc(_fake_plan(tmp_path))
    out = capsys.readouterr().out
    assert f"mentat-session track {session_id}" in out
    assert session_id in out


def test_spawn_with_proc_returns_session_id_and_proc(isolate_logs, tmp_path, monkeypatch):
    monkeypatch.setattr(fan_out, "_emit_event", lambda name, payload: None)
    session_id, proc = fan_out.spawn_with_proc(_fake_plan(tmp_path))
    assert isinstance(session_id, str)
    assert proc is isolate_logs.captured["proc"]


# ── spawn ─────────────────────────────────────────────────────────────────────


def test_spawn_returns_only_session_id(isolate_logs, tmp_path, monkeypatch):
    monkeypatch.setattr(fan_out, "_emit_event", lambda name, payload: None)
    result = fan_out.spawn(_fake_plan(tmp_path))
    assert isinstance(result, str)
    assert re.fullmatch(r"[0-9a-f]{32}", result), f"expected uuid session id, got {result!r}"
