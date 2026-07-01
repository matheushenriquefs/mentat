"""E2E: mentat-session report / doctor / diagnose / list over real seeded sessions.

Drives the actual ``session.py`` command layer in-process over real audit trees under a
temp log root: ``report`` (success-side summary for landed + ejected outcomes and the
latest-session fallback), ``doctor`` (verdict), ``diagnose`` (doctor-first context dump),
and the ``list`` registry in both default active-only and ``--all`` views. Asserts the
persisted summary.md / diagnosis.md and the printed rows. In-process so the session +
sessions + doctor + diagnose modules are measured.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SESSION_DIR = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-session/scripts"
SESSION_PY = SESSION_DIR / "session.py"
TRACK_PY = SESSION_DIR / "track.py"


@pytest.fixture
def repo_log(tmp_path, monkeypatch):
    log_root = tmp_path / "logs"
    repo = "reportrepo"
    (log_root / repo).mkdir(parents=True)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", repo)
    return log_root, repo


def _session():
    return load_script(SESSION_PY, "e2e_session")


def _write_events(session_dir: Path, events: list[dict], *, age: float = 0.0) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    f = session_dir / "events.jsonl"
    f.write_text("".join(json.dumps(e) + "\n" for e in events))
    if age:
        old = time.time() - age
        os.utime(f, (old, old))
        os.utime(session_dir, (old, old))  # latest_session + list read dir mtime


_LANDED = [
    {"ts": "2026-06-30T00:00:00Z", "event": "chunk.spawned",
     "payload": {"slug": "s1", "plan": "s1.md", "harness": "claude-code", "worktree": "/tmp/wt"}},
    {"ts": "2026-06-30T00:00:02Z", "event": "chunk.landed",
     "payload": {"slug": "s1", "sha": "deadbeef", "holding": "main"}},
]

_EJECTED = [
    {"ts": "2026-06-30T00:00:00Z", "event": "chunk.spawned",
     "payload": {"slug": "s2", "plan": "s2.md", "harness": "claude-code", "worktree": "/tmp/wt2"}},
    {"ts": "2026-06-30T00:00:03Z", "event": "chunk.ejected",
     "payload": {"slug": "s2", "reason": "gate-failed", "where": "land"}},
]


def test_report_summarizes_a_landed_session(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-1"
    _write_events(sd, _LANDED)

    assert s.cmd_report("orchestrate-main-1") == 0
    out = capsys.readouterr().out
    assert "Landed" in out and "deadbeef" in out
    assert (sd / "summary.md").exists()
    assert "Landed" in (sd / "summary.md").read_text()


def test_report_summarizes_an_ejected_session(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-2"
    _write_events(sd, _EJECTED)

    assert s.cmd_report("orchestrate-main-2") == 0
    out = capsys.readouterr().out
    assert "Ejected" in out and "gate-failed" in out and "diagnosis.md" in out


def test_report_defaults_to_latest_session(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    _write_events(log_root / repo / "orchestrate-main-old", _LANDED, age=600)
    _write_events(log_root / repo / "orchestrate-main-new", _EJECTED)

    assert s.cmd_report(None) == 0
    assert "Ejected" in capsys.readouterr().out, "bare report must resolve the newest session"


def test_doctor_writes_verdict(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-3"
    _write_events(sd, _LANDED)

    assert s.cmd_doctor("orchestrate-main-3") == 0
    assert "chunk.landed" in capsys.readouterr().out
    assert (sd / "diagnosis.md").exists()


def test_doctor_verdict_hitl_eject_cites_blocker(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-hitl"
    _write_events(sd, [
        {"ts": "2026-06-30T00:00:00Z", "event": "plan.started", "payload": {"path": "tiny.md"}},
        {"ts": "2026-06-30T00:00:01Z", "event": "chunk.ejected",
         "payload": {"slug": "tiny", "reason": "hitl-required", "where": "/wt",
                     "summary": "needs a design call on the API shape"}},
    ])

    assert s.cmd_doctor("orchestrate-main-hitl") == 0
    out = capsys.readouterr().out
    assert "hitl-required" in out
    assert "needs a design call" in out, "the HITL blocker text must surface in the verdict"
    # plan.started (no spawn) supplies the Expected line.
    assert "tiny.md" in out


def test_doctor_verdict_empty_session(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-empty"
    sd.mkdir(parents=True)
    (sd / "events.jsonl").write_text("")  # no rows

    assert s.cmd_doctor("orchestrate-main-empty") == 0
    out = capsys.readouterr().out
    assert "Reason: unknown" in out and "Is regression: unknown" in out


def test_diagnose_dumps_doctor_context(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-4"
    _write_events(sd, _EJECTED)

    assert s.cmd_diagnose("orchestrate-main-4") == 0
    out = capsys.readouterr().out
    assert "diagnose context" in out and "enter diagnose loop" in out
    assert (sd / "diagnosis.md").exists()


def test_list_active_only_hides_old_idle(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    _write_events(log_root / repo / "recent-idle", _LANDED)
    _write_events(log_root / repo / "ancient-idle", _LANDED, age=90000)  # > 24h

    assert s.cmd_list(all_sessions=False) == 0
    out = capsys.readouterr().out
    assert "recent-idle" in out
    assert "ancient-idle" not in out, "default active-only view hides day-old idle sessions"

    assert s.cmd_list(all_sessions=True) == 0
    out = capsys.readouterr().out
    assert "recent-idle" in out and "ancient-idle" in out, "--all shows the full history"


def test_list_empty_repo_reports_none(repo_log, capsys):
    _, _ = repo_log
    s = _session()
    assert s.cmd_list(all_sessions=False) == 0
    assert "no sessions" in capsys.readouterr().out


def test_report_missing_session_errors(repo_log, capsys):
    _, _ = repo_log
    s = _session()
    assert s.cmd_report("does-not-exist") == 1
    assert "not found" in capsys.readouterr().err


def test_doctor_no_sessions_errors(repo_log, capsys):
    _, _ = repo_log
    s = _session()
    # Empty repo dir → latest_session None → error path.
    assert s.cmd_doctor(None) == 1
    assert "no sessions found" in capsys.readouterr().err


def test_track_single_session_view(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    sd = log_root / repo / "orchestrate-main-5"
    _write_events(sd, _LANDED)
    # A harness stream so the transcript renderer produces real content.
    (sd / "session.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "working on it"}]}}) + "\n"
        + json.dumps({"type": "assistant",
                      "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}) + "\n"
    )

    # A named track target renders the one-session transcript view (non-tty one-shot path).
    assert s.cmd_track("orchestrate-main-5") == 0
    assert "working on it" in capsys.readouterr().out

    # A missing named target errors.
    assert s.cmd_track("ghost") == 1
    assert "not found" in capsys.readouterr().err


def test_track_navigator_oneshot_lists_registry(repo_log, capsys):
    log_root, repo = repo_log
    s = _session()
    _write_events(log_root / repo / "orchestrate-main-6", _LANDED)
    _write_events(log_root / repo / "orchestrate-main-7", _EJECTED)

    # cmd_track(None) → navigate(); stdin is not a tty → one-shot registry list print.
    assert s.cmd_track(None, all_sessions=True) == 0
    out = capsys.readouterr().out
    assert "orchestrate-main-6" in out
    assert "orchestrate-main-7" in out


def test_track_render_helpers_over_real_streams(repo_log):
    log_root, repo = repo_log
    track = load_script(TRACK_PY, "e2e_track")
    sd = log_root / repo / "orchestrate-main-8"
    _write_events(sd, _EJECTED)
    (sd / "session.jsonl").write_text(
        json.dumps({"type": "assistant",
                    "message": {"content": [{"type": "text", "text": "hello"},
                                            {"type": "tool_use", "name": "AskUserQuestion", "input": {}}]}}) + "\n"
        + json.dumps({"type": "user",
                      "message": {"content": [{"type": "tool_result", "content": "done"}]}}) + "\n"
    )

    transcript = track.render_transcript_lines(sd)
    assert any("hello" in ln for ln in transcript)
    assert any("AskUserQuestion" in ln for ln in transcript)

    audit = track.render_audit_lines(sd)
    assert any("chunk.ejected" in ln for ln in audit)

    # Empty-state + toggle pure helpers.
    assert track.toggle_view(track._VIEW_TRANSCRIPT) == track._VIEW_AUDIT
    assert "last lifecycle" in track.empty_hint(track._VIEW_AUDIT, "chunk.landed")
