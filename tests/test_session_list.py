"""S6 — `mentat-session list`: repo-wide registry by filesystem scan, status pulled
from the tail event of each session's newest jsonl, attention-ordered. Gate-run home
(testpaths = ["tests"])."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

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


def _write_log(session_dir: Path, name: str, events: list[dict]) -> Path:
    session_dir.mkdir(parents=True, exist_ok=True)
    log_file = session_dir / f"{name}.jsonl"
    with log_file.open("w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return log_file


def _ev(event: str, **payload) -> dict:
    return {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-implement", "event": event, "payload": payload}


# ── derive_status (pure mapping: tail row + age → status) ─────────────────────


def test_derive_status_terminal_is_idle():
    sessions = load_module("sessions")
    assert sessions.derive_status(_ev("chunk.landed", slug="x", sha="a", holding="h"), 9999.0) == "idle"
    assert sessions.derive_status(_ev("plan.succeeded", path="p"), 9999.0) == "idle"


def test_derive_status_nonterminal_fresh_is_working():
    sessions = load_module("sessions")
    assert (
        sessions.derive_status(_ev("gate.evaluated", gate="g", verdict="pass", severity="", message=""), 1.0)
        == "working"
    )


def test_derive_status_nonterminal_stale_is_crashed():
    sessions = load_module("sessions")
    age = sessions.STALE_SECS + 60
    assert sessions.derive_status(_ev("chunk.spawned", slug="x", plan="p", harness="h", worktree="w"), age) == "?"


def test_derive_status_hitl_eject_is_waiting():
    sessions = load_module("sessions")
    row = _ev("chunk.ejected", slug="x", reason="hitl-required", where="impl")
    # even when stale, a hitl-required eject is attention-needing, not crashed
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


def test_list_sessions_full_rank_order(tmp_path):
    """All four ranks present and fully ordered waiting < idle < ? < working."""
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    now = 1_000_000.0
    w = _write_log(repo_dir / "s-waiting", "a", [_ev("chunk.ejected", slug="w", reason="hitl-required", where="impl")])
    i = _write_log(repo_dir / "s-idle", "a", [_ev("chunk.landed", slug="i", sha="s", holding="h")])
    c = _write_log(repo_dir / "s-crashed", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    k = _write_log(repo_dir / "s-working", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    _set_mtime(w, now - 5)
    _set_mtime(i, now - 5)
    _set_mtime(c, now - (sessions.STALE_SECS + 500))  # stale + non-terminal → ?
    _set_mtime(k, now - 5)  # fresh + non-terminal → working

    rows = sessions.list_sessions(repo_dir, now=now)
    assert [r["status"] for r in rows] == ["waiting", "idle", "?", "working"]
    assert [r["session"] for r in rows] == ["s-waiting", "s-idle", "s-crashed", "s-working"]


def test_list_sessions_age_tiebreak_within_rank(tmp_path):
    """Within one rank, the fresher (smaller age) session sorts first."""
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    now = 1_000_000.0
    old = _write_log(repo_dir / "s-old", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    new = _write_log(repo_dir / "s-new", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    _set_mtime(old, now - 100)
    _set_mtime(new, now - 5)
    rows = sessions.list_sessions(repo_dir, now=now)
    assert [r["session"] for r in rows] == ["s-new", "s-old"]  # both working, fresher first


def test_session_status_audit_terminal_beats_newer_stream(tmp_path):
    """A completed session whose harness session.jsonl was touched AFTER its terminal
    audit event must still read idle — completion is judged from the audit stream, not
    from whichever file has the newest mtime."""
    sessions = load_module("sessions")
    session_dir = tmp_path / "s-done"
    audit = _write_log(session_dir, "mentat-implement", [_ev("chunk.landed", slug="d", sha="s", holding="h")])
    stream = session_dir / "session.jsonl"
    stream.write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n"
    )
    _set_mtime(audit, 1000.0)
    _set_mtime(stream, 2000.0)  # newer than the audit terminal event
    assert sessions.newest_jsonl(session_dir).name == "session.jsonl"  # mtime alone would mislead
    assert sessions.session_status(session_dir, 9999.0) == "idle"


def test_list_sessions_survives_vanished_file(tmp_path, monkeypatch):
    """A jsonl deleted between glob and stat must not crash the scan (reaper race)."""
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    _write_log(repo_dir / "s-1", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    real_stat = Path.stat

    def flaky_stat(self, *a, **k):
        if self.name == "a.jsonl":
            raise FileNotFoundError(self)
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    rows = sessions.list_sessions(repo_dir, now=1_000_000.0)  # must not raise
    assert isinstance(rows, list)


def test_list_sessions_killed_shows_crashed(tmp_path):
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    _write_log(
        repo_dir / "implement-dead-9",
        "mentat-implement",
        [_ev("chunk.spawned", slug="d", plan="p", harness="h", worktree="w")],
    )
    rows = sessions.list_sessions(repo_dir, now=9_999_999_999.0, active_only=False)
    assert len(rows) == 1
    assert rows[0]["status"] == "?"
    assert rows[0]["session"] == "implement-dead-9"


def test_list_sessions_empty_repo(tmp_path):
    sessions = load_module("sessions")
    repo_dir = tmp_path / "norepo"
    repo_dir.mkdir()
    assert sessions.list_sessions(repo_dir, now=1.0) == []


def test_list_sessions_records_mtime_and_last_event(tmp_path):
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    _write_log(
        repo_dir / "implement-a-1",
        "mentat-implement",
        [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")],
    )
    log = repo_dir / "implement-a-1" / "mentat-implement.jsonl"
    _set_mtime(log, 1_234_500.0)
    rows = sessions.list_sessions(repo_dir, now=1_234_600.0)
    assert rows[0]["last_event"] == "gate.evaluated"
    # mtime is the file's real st_mtime; age is now - mtime (not just any float)
    assert rows[0]["mtime"] == 1_234_500.0
    assert rows[0]["age"] == 100.0


# ── cmd_list rendering ────────────────────────────────────────────────────────


def test_cmd_list_renders_table(tmp_path):
    session = load_module("session")
    repo_dir = tmp_path / "myrepo"
    _write_log(
        repo_dir / "implement-a-1",
        "mentat-implement",
        [_ev("chunk.ejected", slug="a", reason="hitl-required", where="impl")],
    )
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_REPO": "myrepo"}
    buf = io.StringIO()
    with patch.dict(os.environ, env, clear=False), redirect_stdout(buf):
        rc = session.cmd_list()
    out = buf.getvalue()
    assert rc == 0
    assert "implement-a-1" in out
    assert "waiting" in out


def test_cmd_list_no_sessions(tmp_path):
    session = load_module("session")
    (tmp_path / "myrepo").mkdir()
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_REPO": "myrepo"}
    buf = io.StringIO()
    with patch.dict(os.environ, env, clear=False), redirect_stdout(buf):
        rc = session.cmd_list()
    assert rc == 0
    assert "no sessions" in buf.getvalue().lower()


# ── V6: active_only filter + --all flag ──────────────────────────────────────


def test_list_sessions_active_only_drops_old_idle(tmp_path):
    """active_only=True keeps working/waiting + recent idle, drops old idle + old crashed."""
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    now = 1_000_000.0
    recency = sessions._RECENCY_SECS

    # working (fresh non-terminal) — keep
    w = _write_log(repo_dir / "s-working", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")])
    _set_mtime(w, now - 5)
    # waiting (hitl eject) — keep regardless of age
    wt = _write_log(repo_dir / "s-waiting", "a", [_ev("chunk.ejected", slug="x", reason="hitl-required", where="impl")])
    _set_mtime(wt, now - (recency + 9999))
    # idle, recent — keep
    ir = _write_log(repo_dir / "s-idle-recent", "a", [_ev("chunk.landed", slug="x", sha="s", holding="h")])
    _set_mtime(ir, now - (recency - 100))
    # idle, old — drop
    io_ = _write_log(repo_dir / "s-idle-old", "a", [_ev("chunk.landed", slug="x", sha="s", holding="h")])
    _set_mtime(io_, now - (recency + 100))
    # crashed, old — drop
    co = _write_log(
        repo_dir / "s-crashed-old", "a", [_ev("gate.evaluated", gate="g", verdict="p", severity="", message="")]
    )
    _set_mtime(co, now - (sessions.STALE_SECS + recency + 9999))

    rows_active = sessions.list_sessions(repo_dir, now=now, active_only=True)
    names_active = {r["session"] for r in rows_active}
    assert "s-working" in names_active
    assert "s-waiting" in names_active
    assert "s-idle-recent" in names_active
    assert "s-idle-old" not in names_active
    assert "s-crashed-old" not in names_active

    rows_all = sessions.list_sessions(repo_dir, now=now, active_only=False)
    assert len(rows_all) == 5


def test_cmd_list_all_flag(tmp_path):
    """cmd_list(all_sessions=True) shows old sessions; False hides them."""
    import time

    session = load_module("session")
    sessions = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    recency = sessions._RECENCY_SECS
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_REPO": "myrepo"}

    old = _write_log(repo_dir / "s-old-idle", "a", [_ev("chunk.landed", slug="x", sha="s", holding="h")])
    # Set mtime to 25h ago so it's beyond the recency window
    old_mtime = time.time() - (recency + 3600)
    _set_mtime(old, old_mtime)

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
