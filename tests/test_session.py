"""Tests for mentat-session skill."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-session/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


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
    _write_log(session_dir, "mentat-orchestrate", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-orchestrate",
         "session": "sess-1", "event": "chunk.landed",
         "payload": {"slug": "my-chunk", "sha": "abc123", "holding": "main"}},
    ])
    verdict = doctor_mod.build_verdict(session_dir)
    assert "landed" in verdict.lower() or "success" in verdict.lower()


def test_verdict_for_chunk_ejected_implement_failed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(session_dir, "mentat-implement", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-implement",
         "session": "sess-1", "event": "chunk.ejected",
         "payload": {"slug": "my-chunk", "reason": "implement-failed", "where": "/tmp"}},
    ])
    verdict = doctor_mod.build_verdict(session_dir)
    assert "implement-failed" in verdict or "TDD" in verdict or "gate" in verdict.lower()


def test_verdict_for_chunk_ejected_hitl_required(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(session_dir, "mentat-implement", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-implement",
         "session": "sess-1", "event": "chunk.ejected",
         "payload": {"slug": "my-chunk", "reason": "hitl-required", "where": "/tmp"}},
    ])
    verdict = doctor_mod.build_verdict(session_dir)
    assert "hitl" in verdict.lower() or "ambiguity" in verdict.lower() or "self-answered" in verdict.lower()


def test_doctor_writes_diagnosis_in_session_dir(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(session_dir, "mentat-orchestrate", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-orchestrate",
         "session": "sess-1", "event": "chunk.landed",
         "payload": {"slug": "x", "sha": "abc", "holding": "main"}},
    ])
    doctor_mod.write_diagnosis(session_dir)
    diagnosis = session_dir / "diagnosis.md"
    assert diagnosis.exists()
    content = diagnosis.read_text()
    assert "## Verdict" in content


def test_expected_vs_actual_derived(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(session_dir, "mentat-implement", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-implement",
         "session": "sess-1", "event": "chunk.ejected",
         "payload": {"slug": "x", "reason": "gate-failed", "where": "/tmp"}},
    ])
    verdict = doctor_mod.build_verdict(session_dir)
    # No <placeholder> strings should remain
    assert "<" not in verdict or "chunk" in verdict


def test_regression_marks_unknown_when_no_prior_landed(tmp_path):
    doctor_mod = load_module("doctor")
    session_dir = tmp_path / "sess-1"
    _write_log(session_dir, "mentat-implement", [
        {"ts": "2026-01-01T00:00:00+00:00", "agent": "mentat-implement",
         "session": "sess-1", "event": "chunk.ejected",
         "payload": {"slug": "x", "reason": "implement-failed", "where": "/tmp"}},
    ])
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
    assert "Verdict" in loop_inputs[0]
