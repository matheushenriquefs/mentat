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


def test_build_verdict_returns_markdown(tmp_path):
    from tests.conftest import seed_agent_events

    diag = load_module("diagnose")
    sd = seed_agent_events(
        tmp_path,
        "testrepo",
        "sess-1",
        [{"ts": "t0", "event": "chunk.landed", "payload": {"slug": "x", "sha": "a", "holding": "h"}}],
    )
    text = diag.build_verdict(sd)
    assert "## Verdict" in text
    assert "chunk.landed" in text


def test_run_diagnose_wires_verdict_into_loop(tmp_path, monkeypatch, capsys):
    diag = load_module("diagnose")
    monkeypatch.setattr(diag, "build_verdict", lambda sd: "DOCTOR-BODY")
    diag.run_diagnose(tmp_path / "sess-1")
    assert "DOCTOR-BODY" in capsys.readouterr().out
