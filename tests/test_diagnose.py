"""mentat-track diagnose: verdict from the canonical store, then the /diagnose loop."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.conftest import load_script

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-track/scripts"
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
        [{"ts": "t0", "event": "chunk_landed", "payload": {"slug": "x", "sha": "a", "holding": "h"}}],
    )
    text = diag.build_verdict(sd)
    assert "## Verdict" in text
    assert "chunk_landed" in text


def test_run_diagnose_wires_verdict_into_loop(tmp_path, monkeypatch, capsys):
    diag = load_module("diagnose")
    monkeypatch.setattr(diag, "build_verdict", lambda sd: "DOCTOR-BODY")
    diag.run_diagnose(tmp_path / "sess-1")
    assert "DOCTOR-BODY" in capsys.readouterr().out


def test_suspect_map_covers_all_chunk_eject_reasons():
    from lib import events

    diag = load_module("diagnose")
    assert set(diag._SUSPECT_MAP) == events.CHUNK_EJECT_REASONS


def test_build_verdict_no_unknown_for_catalog_reasons(tmp_path):
    from lib import events

    from tests.conftest import seed_agent_events

    diag = load_module("diagnose")
    for reason in sorted(events.CHUNK_EJECT_REASONS):
        sd = seed_agent_events(
            tmp_path,
            "testrepo",
            f"sess-{reason}",
            [
                {
                    "ts": "t0",
                    "event": "chunk_ejected",
                    "payload": {"slug": "x", "reason": reason, "where": "/wt"},
                }
            ],
        )
        text = diag.build_verdict(sd)
        assert "Unknown reason" not in text
        assert reason in text
