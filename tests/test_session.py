"""Tests for mentat-session skill."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-session/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def _write_log(session_dir: Path, agent: str, events: list[dict]) -> Path:
    log_file = session_dir / f"{agent}-manual.jsonl"
    session_dir.mkdir(parents=True, exist_ok=True)
    with log_file.open("w") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return log_file


def test_latest_session_excludes_manual(tmp_path):
    sessions_mod = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    (repo_dir / "manual").mkdir(parents=True)
    (repo_dir / "sess-1").mkdir()
    session = sessions_mod.latest_session(repo_dir)
    assert session == "sess-1"


def test_chunks_in_session_lists_all(tmp_path):
    sessions_mod = load_module("sessions")
    repo_dir = tmp_path / "myrepo"
    session_dir = repo_dir / "sess-1"
    session_dir.mkdir(parents=True)
    (session_dir / "mentat-plan-chunk1.jsonl").write_text("{}\n")
    (session_dir / "mentat-implement-chunk2.jsonl").write_text("{}\n")
    chunks = sessions_mod.chunks_in_session(session_dir)
    assert len(chunks) == 2


def test_verdict_for_chunk_landed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-orchestrate",
                "session": "sess-1",
                "event": "chunk.landed",
                "payload": {"slug": "my-chunk", "sha": "abc123", "holding": "main"},
            },
        ],
    )
    verdict = doctor_mod.build_verdict(session_dir)
    assert "landed" in verdict.lower() or "success" in verdict.lower()


def test_verdict_for_chunk_ejected_implement_failed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-implement",
                "session": "sess-1",
                "event": "chunk.ejected",
                "payload": {"slug": "my-chunk", "reason": "implement-failed", "where": "/tmp"},
            },
        ],
    )
    verdict = doctor_mod.build_verdict(session_dir)
    assert "implement-failed" in verdict or "TDD" in verdict or "gate" in verdict.lower()


def test_verdict_for_chunk_ejected_hitl_required(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-implement",
                "session": "sess-1",
                "event": "chunk.ejected",
                "payload": {"slug": "my-chunk", "reason": "hitl-required", "where": "/tmp"},
            },
        ],
    )
    verdict = doctor_mod.build_verdict(session_dir)
    assert "hitl" in verdict.lower() or "ambiguity" in verdict.lower() or "self-answered" in verdict.lower()


def test_doctor_writes_diagnosis_in_session_dir(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-orchestrate",
                "session": "sess-1",
                "event": "chunk.landed",
                "payload": {"slug": "x", "sha": "abc", "holding": "main"},
            },
        ],
    )
    doctor_mod.write_diagnosis(session_dir)
    diagnosis = session_dir / "diagnosis.md"
    assert diagnosis.exists()
    content = diagnosis.read_text()
    assert "## Verdict" in content


# ── S8: success-side report-back summary ─────────────────────────────────────


def test_summary_for_chunk_landed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-orchestrate",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.landed",
                "payload": {"slug": "my-chunk", "sha": "abc123", "holding": "main"},
            },
        ],
    )
    summary = doctor_mod.build_summary(session_dir)
    assert "my-chunk" in summary
    assert "abc123" in summary


def test_summary_for_chunk_ejected_carries_failure(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.ejected",
                "payload": {"slug": "my-chunk", "reason": "gate-failed", "where": "/x"},
            },
        ],
    )
    summary = doctor_mod.build_summary(session_dir)
    assert "gate-failed" in summary


def test_write_summary_writes_summary_md(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.landed",
                "payload": {"slug": "c", "sha": "deadbee", "holding": "main"},
            },
        ],
    )
    out = doctor_mod.write_summary(session_dir)
    assert out == session_dir / "summary.md"
    assert out.exists()
    assert "deadbee" in out.read_text()


def test_report_prints_success_summary(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    session_dir = tmp_path / "logs" / "myrepo" / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.landed",
                "payload": {"slug": "c", "sha": "abc999", "holding": "main"},
            },
        ],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_mod.cmd_report("sess-1")
    assert rc == 0
    assert "abc999" in buf.getvalue()


def test_report_shows_failure_for_ejected(tmp_path, monkeypatch):
    session_mod = load_module("session")
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    session_dir = tmp_path / "logs" / "myrepo" / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "event": "chunk.ejected",
                "payload": {"slug": "c", "reason": "gate-failed", "where": "/x"},
            },
        ],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = session_mod.cmd_report("sess-1")
    assert rc == 0
    assert "gate-failed" in buf.getvalue()


def test_expected_vs_actual_derived(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-implement",
                "session": "sess-1",
                "event": "chunk.ejected",
                "payload": {"slug": "x", "reason": "gate-failed", "where": "/tmp"},
            },
        ],
    )
    verdict = doctor_mod.build_verdict(session_dir)
    # <where> placeholder must be filled in; no unfilled angle-bracket placeholders
    assert "<where>" not in verdict


def test_regression_marks_unknown_when_no_prior_landed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(
        session_dir,
        "mentat-implement",
        [
            {
                "ts": "2026-01-01T00:00:00+00:00",
                "agent": "mentat-implement",
                "session": "sess-1",
                "event": "chunk.ejected",
                "payload": {"slug": "x", "reason": "implement-failed", "where": "/tmp"},
            },
        ],
    )
    verdict = doctor_mod.build_verdict(session_dir)
    assert "unknown" in verdict.lower()


def test_diagnose_calls_doctor_first(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = tmp_path / "sess-1"
    session_dir.mkdir(parents=True)

    doctor_calls = []

    def fake_write(sd):
        doctor_calls.append(sd)
        return "## Verdict\n- Reason: landed\n"

    with patch.object(diag_mod, "_call_doctor", side_effect=fake_write):
        with patch.object(diag_mod, "_run_diagnose_loop", return_value=None):
            diag_mod.run_diagnose(session_dir)

    assert doctor_calls


def test_diagnose_feeds_doctor_output_into_loop(tmp_path):
    diag_mod = load_module("diagnose")
    session_dir = tmp_path / "sess-1"
    session_dir.mkdir(parents=True)

    loop_inputs: list[str] = []

    def fake_loop(context: str) -> None:
        loop_inputs.append(context)

    with patch.object(diag_mod, "_call_doctor", return_value="## Verdict\n- Reason: ejected\n"):
        with patch.object(diag_mod, "_run_diagnose_loop", side_effect=fake_loop):
            diag_mod.run_diagnose(session_dir)

    assert loop_inputs


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
    session_dir = log_root / "testrepo" / "sess-abc"
    session_dir.mkdir(parents=True)
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
    session_mod, log_root = _make_session_env(tmp_path, monkeypatch)
    session_dir = log_root / "testrepo" / "sess-doc"
    session_dir.mkdir(parents=True)
    fake_diag = session_dir / "diagnosis.md"
    fake_diag.write_text("## Verdict\n- landed\n")
    buf = io.StringIO()
    with patch.object(session_mod._doctor, "write_diagnosis", return_value=fake_diag):
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
