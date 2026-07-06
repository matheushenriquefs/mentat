"""Tests for mentat-session skill."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script, seed_agent_events

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-session/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _write_log(
    tmp_path: Path,
    session_id: str,
    harness: str,
    events: list[dict],
    *,
    repo: str = "testrepo",
) -> Path:
    return seed_agent_events(tmp_path, repo, session_id, events, harness=harness)


def test_latest_session_excludes_manual(tmp_path, monkeypatch):
    sessions_mod = load_module("sessions")
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    repo_dir = tmp_path / "logs" / "myrepo"
    (repo_dir / "manual").mkdir(parents=True)
    seed_agent_events(
        tmp_path,
        "myrepo",
        "sess-1",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "x", "sha": "a", "holding": "h"},
            }
        ],
    )
    session = sessions_mod.latest_session(repo_dir)
    assert session == "sess-1"


def test_verdict_for_chunk_landed(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "my-chunk", "sha": "abc123", "holding": "main"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "landed" in verdict.lower() or "success" in verdict.lower()


def test_verdict_for_chunk_ejected_implement_failed(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "my-chunk", "reason": "implement_failed", "where": "/tmp"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "implement_failed" in verdict or "TDD" in verdict or "gate" in verdict.lower()


def test_verdict_for_chunk_ejected_hitl_required(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "my-chunk", "reason": "hitl_required", "where": "/tmp"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "hitl" in verdict.lower() or "ambiguity" in verdict.lower() or "self-answered" in verdict.lower()


def test_verdict_for_worker_died_names_slug_and_reason(tmp_path):
    """A worker-died eject must attribute the dead chunk by slug + reason, never
    fall through to an "Unknown reason" suspect (S5)."""
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "dead-chunk", "reason": "worker_died", "where": "/tmp/wt"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "worker_died" in verdict
    assert "dead-chunk" in verdict
    assert "Unknown reason" not in verdict
    assert "Suspect: None" not in verdict


def test_verdict_worker_died_not_masked_by_later_land(tmp_path):
    """Batch session, two chunks: one lands, another's worker died earlier. The
    reversed-by-ts scan must not report 'chunk_landed / Suspect: None' and bury
    the dead worker — the eject is the story doctor exists to tell (S5)."""
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:01+00:00",
                "event": "chunk_started",
                "payload": {"slug": "dead-chunk", "plan": "dead.md", "harness": "cc", "worktree": "/tmp/wt"},
            },
            {
                "ts": "2026-01-01T00:00:02+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "dead-chunk", "reason": "worker_died", "where": "/tmp/wt"},
            },
            {
                "ts": "2026-01-01T00:00:03+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "good-chunk", "sha": "abc123", "holding": "main"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "Reason: chunk_landed" not in verdict
    assert "Suspect: None" not in verdict
    assert "worker_died" in verdict
    assert "dead-chunk" in verdict


def test_doctor_writes_diagnosis_in_session_dir(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_REPO", "testrepo")
    _write_log(
        tmp_path,
        "sess-1",
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "x", "sha": "abc", "holding": "main"},
            },
        ],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_mod.cmd_doctor("sess-1")
    assert rc == 0
    assert "## Verdict" in buf.getvalue()


# ── S8: success-side report-back summary ─────────────────────────────────────


def test_summary_for_chunk_landed(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "my-chunk", "sha": "abc123", "holding": "main"},
            },
        ],
    )
    summary = diag_mod.build_summary(session_dir)
    assert "my-chunk" in summary
    assert "abc123" in summary


def test_summary_for_chunk_ejected_carries_failure(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "my-chunk", "reason": "gate_failed", "where": "/x"},
            },
        ],
    )
    summary = diag_mod.build_summary(session_dir)
    assert "gate_failed" in summary


def test_write_summary_writes_summary_md(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "c", "sha": "deadbee", "holding": "main"},
            },
        ],
    )
    out = diag_mod.write_summary(session_dir)
    assert out == session_dir / "summary.md"
    assert out.exists()
    assert "deadbee" in out.read_text()


def test_report_prints_success_summary(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "c", "sha": "abc999", "holding": "main"},
            },
        ],
        repo="myrepo",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_mod.cmd_report("sess-1")
    assert rc == 0
    assert "abc999" in buf.getvalue()


def test_report_shows_failure_for_ejected(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "c", "reason": "gate_failed", "where": "/x"},
            },
        ],
        repo="myrepo",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_mod.cmd_report("sess-1")
    assert rc == 0
    assert "gate_failed" in buf.getvalue()


def test_expected_vs_actual_derived(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "x", "reason": "gate_failed", "where": "/tmp"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "<where>" not in verdict


def test_regression_marks_unknown_when_no_prior_landed(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "sess-1",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "x", "reason": "implement_failed", "where": "/tmp"},
            },
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "unknown" in verdict.lower()


def test_diagnose_calls_doctor_first(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = tmp_path / "sess-1"
    session_dir.mkdir(parents=True)

    verdict_calls: list[Path] = []

    def fake_verdict(sd: Path) -> str:
        verdict_calls.append(sd)
        return "## Verdict\n- Reason: landed\n"

    with patch.object(diag_mod, "build_verdict", side_effect=fake_verdict):
        with patch.object(diag_mod, "_run_diagnose_loop", return_value=None):
            diag_mod.run_diagnose(session_dir)

    assert verdict_calls == [session_dir]


def test_diagnose_feeds_doctor_output_into_loop(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = tmp_path / "sess-1"
    session_dir.mkdir(parents=True)

    loop_inputs: list[str] = []

    def fake_loop(context: str) -> None:
        loop_inputs.append(context)

    with patch.object(diag_mod, "build_verdict", return_value="## Verdict\n- Reason: ejected\n"):
        with patch.object(diag_mod, "_run_diagnose_loop", side_effect=fake_loop):
            diag_mod.run_diagnose(session_dir)

    assert loop_inputs == ["## Verdict\n- Reason: ejected\n"]


# ── session.py dispatcher branches ───────────────────────────────────────────


def _make_session_env(tmp_path: Path, monkeypatch) -> tuple:
    """Return (session_mod, log_root) with env vars pointing to tmp dirs."""
    session_mod = load_module("session")
    log_root = tmp_path / "logs"
    log_root.mkdir()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_root))
    monkeypatch.setenv("MENTAT_REPO", "testrepo")
    return session_mod, log_root


def test_cmd_track_no_session_id_calls_navigate(tmp_path, monkeypatch):
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    (log_root / "testrepo").mkdir()
    navigate_calls: list = []
    with patch.object(session_mod._track, "navigate", side_effect=lambda *a, **kw: navigate_calls.append(kw) or 0):
        rc = session_mod.cmd_track(None)
    assert rc == 0
    assert navigate_calls


def test_cmd_track_session_not_found_returns_1(tmp_path, monkeypatch):
    session_mod, _ = _make_session_env(tmp_path, monkeypatch)
    rc = session_mod.cmd_track("nonexistent-session-xyz")
    assert rc == 1


def test_cmd_track_session_found_calls_view_session(tmp_path, monkeypatch):
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    from lib import store

    session_dir = log_root / "testrepo" / "sess-abc"
    session_dir.mkdir(parents=True)
    store.record_emit(
        {"MENTAT_AGENT": "sess-abc", "MENTAT_AGENT_PID": "1", "MENTAT_HARNESS": "cursor"},
        "chunk_started",
        {"slug": "x"},
    )
    view_calls: list = []
    with patch.object(session_mod._track, "view_session", side_effect=lambda sd: view_calls.append(sd)):
        rc = session_mod.cmd_track("sess-abc")
    assert rc == 0
    assert view_calls


def test_resolve_session_no_sessions_returns_1(tmp_path, monkeypatch):
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    (log_root / "testrepo").mkdir()
    result = session_mod._resolve_session(None)
    assert result == 1


def test_resolve_session_dir_not_found_returns_1(tmp_path, monkeypatch):
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    (log_root / "testrepo").mkdir()
    result = session_mod._resolve_session("does-not-exist-xyz")
    assert result == 1


def test_cmd_doctor_invalid_session_returns_1(tmp_path, monkeypatch):
    session_mod, _ = _make_session_env(tmp_path, monkeypatch)
    rc = session_mod.cmd_doctor("no-such-session")
    assert rc == 1


def test_cmd_doctor_valid_session_writes_diagnosis(tmp_path, monkeypatch):
    session_mod, _ = _make_session_env(tmp_path, monkeypatch)
    seed_agent_events(
        tmp_path,
        "testrepo",
        "sess-doc",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_landed",
                "payload": {"slug": "x", "sha": "a", "holding": "h"},
            }
        ],
    )
    buf = io.StringIO()
    with patch.object(session_mod._diagnose, "build_verdict", return_value="## Verdict\n- landed\n"):
        with redirect_stdout(buf):
            rc = session_mod.cmd_doctor("sess-doc")
    assert rc == 0
    assert "Verdict" in buf.getvalue()


def test_cmd_report_invalid_session_returns_1(tmp_path, monkeypatch):
    session_mod, _ = _make_session_env(tmp_path, monkeypatch)
    rc = session_mod.cmd_report("no-such-session")
    assert rc == 1


def test_cmd_diagnose_invalid_session_returns_1(tmp_path, monkeypatch):
    session_mod, _ = _make_session_env(tmp_path, monkeypatch)
    rc = session_mod.cmd_diagnose("no-such-session")
    assert rc == 1


def test_cmd_diagnose_valid_session_calls_run_diagnose(tmp_path, monkeypatch):
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    session_dir = log_root / "testrepo" / "sess-diag"
    session_dir.mkdir(parents=True)
    calls: list = []
    with patch.object(session_mod._diagnose, "run_diagnose", side_effect=lambda sd: calls.append(sd)):
        rc = session_mod.cmd_diagnose("sess-diag")
    assert rc == 0
    assert calls


# ── _humanize_age branches ────────────────────────────────────────────────────


def test_humanize_age_seconds():
    session_mod = load_module("session")
    assert session_mod._humanize_age(45) == "45s ago"


def test_humanize_age_minutes():
    session_mod = load_module("session")
    assert session_mod._humanize_age(120) == "2m ago"


def test_humanize_age_hours():
    session_mod = load_module("session")
    assert session_mod._humanize_age(7200) == "2h ago"


def test_humanize_age_days():
    session_mod = load_module("session")
    assert session_mod._humanize_age(172800) == "2d ago"


# ── main() dispatch ───────────────────────────────────────────────────────────


def test_main_dispatches_list(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "testrepo")
    (tmp_path / "logs" / "testrepo").mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["session.py", "list"])
    import pytest as _pytest

    with _pytest.raises(SystemExit) as exc:
        session_mod.main()
    assert exc.value.code == 0


def test_main_dispatches_track_no_session(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "testrepo")
    (tmp_path / "logs" / "testrepo").mkdir(parents=True)
    monkeypatch.setattr("sys.argv", ["session.py", "track"])
    import pytest as _pytest

    with patch.object(session_mod._track, "navigate", return_value=0):
        with _pytest.raises(SystemExit) as exc:
            session_mod.main()
    assert exc.value.code == 0


# ── doctor edge branches: empty / no-terminal / HITL blocker ─────────────────


def test_verdict_empty_events_is_all_unknown(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = tmp_path / "empty"
    session_dir.mkdir()
    verdict = diag_mod.build_verdict(session_dir)
    assert "Reason: unknown" in verdict
    assert "Is regression: unknown" in verdict


def test_verdict_events_without_terminal_reports_no_terminal(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "no-terminal",
        "mentat-implement",
        [{"ts": "2026-01-01T00:00:00+00:00", "event": "chunk_started", "payload": {"path": "/p.md"}}],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "No terminal event found." in verdict
    assert "Reason: unknown" in verdict


def test_verdict_hitl_blocker_appended_to_suspect(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "hitl",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "c", "reason": "hitl_required", "where": "/wt", "summary": "need a decision"},
            }
        ],
    )
    verdict = diag_mod.build_verdict(session_dir)
    assert "Blocker: need a decision" in verdict


def test_summary_no_terminal_says_completed_in_session(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "insession",
        "mentat-implement",
        [{"ts": "2026-01-01T00:00:00+00:00", "event": "chunk_started", "payload": {"slug": "c"}}],
    )
    summary = diag_mod.build_summary(session_dir)
    assert "not yet landed" in summary


def test_summary_hitl_blocker_appended(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = _write_log(
        tmp_path,
        "hitl-sum",
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk_ejected",
                "payload": {"slug": "c", "reason": "hitl_required", "summary": "blocked here"},
            }
        ],
    )
    summary = diag_mod.build_summary(session_dir)
    assert "Blocker: blocked here" in summary


# ── sessions: row-parse robustness (non-dict JSON skipped) ───────────────────


def test_iter_rows_from_text_skips_non_dict_and_garbage():
    sessions_mod = load_module("sessions")
    text = '{"a": 1}\n[1, 2, 3]\nnot json\n\n"bare string"\n{"b": 2}\n'
    rows = list(sessions_mod.iter_rows_from_text(text))
    assert rows == [{"a": 1}, {"b": 2}]


def test_list_sessions_empty_when_repo_dir_missing(tmp_path):
    sessions_mod = load_module("sessions")
    assert sessions_mod.list_sessions(tmp_path / "nope") == []


def test_status_from_signals_waiting_on_ask_user_question():
    sessions_mod = load_module("sessions")
    waiting = {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion"}]}}
    assert sessions_mod._status_from_signals(None, waiting, 1.0) == "waiting"


def test_session_worktree_ignores_non_dict_and_non_str_payload(tmp_path):
    sessions_mod = load_module("sessions")
    sd = tmp_path / "s-wt"
    sd.mkdir()
    rows = [
        {"ts": "1", "event": "chunk_started", "payload": "not-a-dict"},
        {"ts": "2", "event": "chunk_started", "payload": {"worktree": 123}},
    ]
    (sd / "audit.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert sessions_mod.session_worktree(sd) is None


def test_build_record_none_for_vanished_session_dir(tmp_path):
    """A dir removed mid-scan has no mtime → _build_record returns None, never raises."""
    sessions_mod = load_module("sessions")
    assert sessions_mod._build_record(tmp_path / "gone", clock=0.0, stale_secs=300) is None
