"""mentat-session diagnose: doctor-first context, then the /diagnose loop entry."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-session/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_run_diagnose_loop_prints_context(capsys):
    diag = load_module("diagnose")
    diag._run_diagnose_loop("CTX-BODY")
    out = capsys.readouterr().out
    assert "diagnose context" in out
    assert "CTX-BODY" in out
    assert "enter diagnose loop" in out


def test_call_doctor_reads_written_diagnosis(tmp_path, monkeypatch):
    diag = load_module("diagnose")
    f = tmp_path / "diagnosis.md"
    f.write_text("DIAG-TEXT")
    monkeypatch.setattr(diag._doctor, "write_diagnosis", lambda sd: f)
    assert diag._call_doctor(tmp_path) == "DIAG-TEXT"


def test_run_diagnose_wires_doctor_into_loop(tmp_path, monkeypatch, capsys):
    diag = load_module("diagnose")
    f = tmp_path / "diagnosis.md"
    f.write_text("DOCTOR-BODY")
    monkeypatch.setattr(diag._doctor, "write_diagnosis", lambda sd: f)
    diag.run_diagnose(tmp_path)
    assert "DOCTOR-BODY" in capsys.readouterr().out
