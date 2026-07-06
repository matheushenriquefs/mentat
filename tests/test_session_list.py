"""S6 — `mentat-session list`: repo-wide agent registry from the canonical store."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script, seed_agent_events

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-session/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))
from lib import harness_stream  # noqa: E402


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


# ── lib.harness_stream — single owner of the AskUserQuestion wire schema ──────


def test_harness_stream_detects_ask_user_question():
    row = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}}
    assert harness_stream.is_ask_user_question(row) is True


def test_harness_stream_rejects_non_ask_rows():
    assert (
        harness_stream.is_ask_user_question({"type": "assistant", "message": {"content": [{"type": "text"}]}}) is False
    )
    assert harness_stream.is_ask_user_question({"type": "user"}) is False
    assert harness_stream.is_ask_user_question("not a dict") is False
    assert harness_stream.is_ask_user_question({"type": "assistant", "message": {"content": "bad"}}) is False


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _write_log(tmp_path: Path, agent_id: str, events: list[dict], *, repo: str = "myrepo") -> Path:
    return seed_agent_events(tmp_path, repo, agent_id, events)


def _ev(event: str, epoch: float, **payload) -> dict:
    return {"ts": _ts(epoch), "event": event, "payload": payload}


# ── derive_status (pure mapping: tail row + age → status) ─────────────────────


def test_derive_status_terminal_is_idle():
    sessions = load_module("sessions")
    assert sessions.derive_status(_ev("chunk.landed", 0, slug="x", sha="a", holding="h"), 9999.0) == "idle"
    assert sessions.derive_status(_ev("plan.succeeded", 0, path="p"), 9999.0) == "idle"


def test_derive_status_nonterminal_fresh_is_working():
    sessions = load_module("sessions")
    assert (
        sessions.derive_status(_ev("gate.evaluated", 0, gate="g", verdict="pass", severity="", message=""), 1.0)
        == "working"
    )


def test_derive_status_nonterminal_stale_is_crashed():
    sessions = load_module("sessions")
    age = sessions.STALE_SECS + 60
    assert sessions.derive_status(_ev("chunk.spawned", 0, slug="x", plan="p", harness="h", worktree="w"), age) == "?"


def test_derive_status_hitl_eject_is_waiting():
    sessions = load_module("sessions")
    row = _ev("chunk.ejected", 0, slug="x", reason="hitl_required", where="impl")
    assert sessions.derive_status(row, sessions.STALE_SECS + 999) == "waiting"


def test_derive_status_waiting_stream_askuserquestion():
    sessions = load_module("sessions")
    stream_row = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion"}]},
    }
    assert sessions.derive_status(stream_row, 1.0) == "waiting"


def test_derive_status_empty_is_crashed_when_stale():
    sessions = load_module("sessions")
    assert sessions.derive_status(None, sessions.STALE_SECS + 1) == "?"


# ── list_sessions (registry scan + attention ordering) ────────────────────────


def _set_mtime(log_file: Path, mtime: float) -> None:
    os.utime(log_file, (mtime, mtime))


def test_list_sessions_full_rank_order(tmp_path, monkeypatch):
    """All four ranks present and fully ordered waiting < idle < ? < working."""
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    now = 1_000_000.0
    _write_log(
        tmp_path,
        "s-waiting",
        [_ev("chunk.ejected", now - 5, slug="w", reason="hitl_required", where="impl")],
    )
    _write_log(
        tmp_path,
        "s-idle",
        [_ev("chunk.landed", now - 5, slug="i", sha="s", holding="h")],
    )
    _write_log(
        tmp_path,
        "s-crashed",
        [_ev("gate.evaluated", now - (sessions.STALE_SECS + 500), gate="g", verdict="p", severity="", message="")],
    )
    _write_log(
        tmp_path,
        "s-working",
        [_ev("gate.evaluated", now - 5, gate="g", verdict="p", severity="", message="")],
    )

    rows = sessions.list_sessions(repo_dir, now=now)
    assert [r["status"] for r in rows] == ["waiting", "idle", "?", "working"]
    assert [r["session"] for r in rows] == ["s-waiting", "s-idle", "s-crashed", "s-working"]


def test_list_sessions_age_tiebreak_within_rank(tmp_path, monkeypatch):
    """Within one rank, the fresher (smaller age) session sorts first."""
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    now = 1_000_000.0
    _write_log(
        tmp_path,
        "s-old",
        [_ev("gate.evaluated", now - 100, gate="g", verdict="p", severity="", message="")],
    )
    _write_log(
        tmp_path,
        "s-new",
        [_ev("gate.evaluated", now - 5, gate="g", verdict="p", severity="", message="")],
    )
    rows = sessions.list_sessions(repo_dir, now=now)
    assert [r["session"] for r in rows] == ["s-new", "s-old"]


def test_session_status_audit_terminal_beats_newer_stream(tmp_path):
    """A completed session whose harness session.jsonl was touched AFTER its terminal
    audit event must still read idle — completion is judged from the audit stream, not
    from whichever file has the newest mtime."""
    sessions = load_module("sessions")
    session_dir = tmp_path / "s-done"
    session_dir.mkdir(parents=True)
    audit = session_dir / "mentat-implement.jsonl"
    audit.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.landed",
                "payload": {"slug": "d", "sha": "s", "holding": "h"},
            }
        )
        + "\n"
    )
    stream = session_dir / "session.jsonl"
    stream.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n"
    )
    _set_mtime(audit, 1000.0)
    _set_mtime(stream, 2000.0)
    assert sessions.newest_jsonl(session_dir).name == "session.jsonl"
    assert sessions.session_status(session_dir, 9999.0) == "idle"


def test_list_sessions_survives_vanished_file(tmp_path, monkeypatch):
    """Store-backed registry scan must not raise when log dirs are present."""
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    _write_log(
        tmp_path,
        "s-1",
        [_ev("gate.evaluated", 1_000_000.0, gate="g", verdict="p", severity="", message="")],
    )
    rows = sessions.list_sessions(repo_dir, now=1_000_000.0)
    assert isinstance(rows, list)


def test_list_sessions_killed_shows_crashed(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    now = 9_999_999_999.0
    _write_log(
        tmp_path,
        "implement-dead-9",
        [_ev("chunk.spawned", now - (sessions.STALE_SECS + 60), slug="d", plan="p", harness="h", worktree="w")],
    )
    rows = sessions.list_sessions(repo_dir, now=now, active_only=False)
    assert len(rows) == 1
    assert rows[0]["status"] == "?"
    assert rows[0]["session"] == "implement-dead-9"


def test_list_sessions_empty_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    repo_dir.mkdir(parents=True)
    assert sessions.list_sessions(repo_dir, now=1.0) == []


def test_list_sessions_records_mtime_and_last_event(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    event_ts = 1_234_500.0
    _write_log(
        tmp_path,
        "implement-a-1",
        [_ev("gate.evaluated", event_ts, gate="g", verdict="p", severity="", message="")],
    )
    rows = sessions.list_sessions(repo_dir, now=1_234_600.0)
    assert rows[0]["last_event"] == "gate.evaluated"
    assert rows[0]["mtime"] == event_ts
    assert rows[0]["age"] == 100.0


# ── cmd_list rendering ────────────────────────────────────────────────────────


def test_cmd_list_renders_table(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    session = load_module("session")
    _write_log(
        tmp_path,
        "implement-a-1",
        [_ev("chunk.ejected", 1_000_000.0, slug="a", reason="hitl_required", where="impl")],
    )
    env = {"MENTAT_LOG_PATH": str(tmp_path / "logs"), "MENTAT_REPO": "myrepo"}
    buf = io.StringIO()
    with patch.dict(os.environ, env, clear=False), redirect_stdout(buf):
        rc = session.cmd_list()
    out = buf.getvalue()
    assert rc == 0
    assert "implement-a-1" in out
    assert "waiting" in out


def test_cmd_list_no_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    session = load_module("session")
    (tmp_path / "logs" / "myrepo").mkdir(parents=True)
    env = {"MENTAT_LOG_PATH": str(tmp_path / "logs"), "MENTAT_REPO": "myrepo"}
    buf = io.StringIO()
    with patch.dict(os.environ, env, clear=False), redirect_stdout(buf):
        rc = session.cmd_list()
    assert rc == 0
    assert "no sessions" in buf.getvalue().lower()


# ── V6: active_only filter + --all flag ──────────────────────────────────────


def test_list_sessions_active_only_drops_old_idle(tmp_path, monkeypatch):
    """active_only=True keeps working/waiting + recent idle, drops old idle + old crashed."""
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "logs" / "myrepo"
    now = 1_000_000.0
    recency = sessions._RECENCY_SECS

    _write_log(
        tmp_path,
        "s-working",
        [_ev("gate.evaluated", now - 5, gate="g", verdict="p", severity="", message="")],
    )
    _write_log(
        tmp_path,
        "s-waiting",
        [_ev("chunk.ejected", now - (recency + 9999), slug="x", reason="hitl_required", where="impl")],
    )
    _write_log(
        tmp_path,
        "s-idle-recent",
        [_ev("chunk.landed", now - (recency - 100), slug="x", sha="s", holding="h")],
    )
    _write_log(
        tmp_path,
        "s-idle-old",
        [_ev("chunk.landed", now - (recency + 100), slug="x", sha="s", holding="h")],
    )
    _write_log(
        tmp_path,
        "s-crashed-old",
        [
            _ev(
                "gate.evaluated",
                now - (sessions.STALE_SECS + recency + 9999),
                gate="g",
                verdict="p",
                severity="",
                message="",
            )
        ],
    )

    rows_active = sessions.list_sessions(repo_dir, now=now, active_only=True)
    names_active = {r["session"] for r in rows_active}
    assert "s-working" in names_active
    assert "s-waiting" in names_active
    assert "s-idle-recent" in names_active
    assert "s-idle-old" not in names_active
    assert "s-crashed-old" not in names_active

    rows_all = sessions.list_sessions(repo_dir, now=now, active_only=False)
    assert len(rows_all) == 5


def test_cmd_list_all_flag(tmp_path, monkeypatch):
    """cmd_list(all_sessions=True) shows old sessions; False hides them."""
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    session = load_module("session")
    sessions = load_module("sessions")
    recency = sessions._RECENCY_SECS
    now = 1_000_000.0
    env = {"MENTAT_LOG_PATH": str(tmp_path / "logs"), "MENTAT_REPO": "myrepo"}

    _write_log(
        tmp_path,
        "s-old-idle",
        [_ev("chunk.landed", now - (recency + 3600), slug="x", sha="s", holding="h")],
    )

    buf_active = io.StringIO()
    buf_all = io.StringIO()
    with patch.dict(os.environ, env, clear=False):
        with redirect_stdout(buf_active):
            session.cmd_list(all_sessions=False)
        with redirect_stdout(buf_all):
            session.cmd_list(all_sessions=True)
    assert "s-old-idle" not in buf_active.getvalue()
    assert "s-old-idle" in buf_all.getvalue()


def test_build_parser_list_has_all_flag():
    session = load_module("session")
    p = session.build_parser()
    args = p.parse_args(["list", "--all"])
    assert args.all_sessions is True


def test_build_parser_track_has_all_flag():
    session = load_module("session")
    p = session.build_parser()
    args = p.parse_args(["track", "--all"])
    assert args.all_sessions is True
