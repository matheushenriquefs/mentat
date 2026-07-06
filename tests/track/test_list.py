"""Track list cmd — real store round-trips (ADR-0020)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from lib import store  # noqa: E402
from tests.conftest import load_script  # noqa: E402

_TRACK = REPO_ROOT / ".agents/skills/mentat-track/scripts/track.py"


def test_cmd_list_shows_agent_from_real_store(
    real_audit_store: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load_script(_TRACK, "track_list_mirror")
    repo = "mentat"
    agent_id = "track-list-live"
    monkeypatch.setenv("MENTAT_REPO", repo)
    store.record_emit(
        {
            "MENTAT_AGENT": agent_id,
            "MENTAT_AGENT_PID": str(os.getpid()),
            "MENTAT_HARNESS": "cursor",
            "MENTAT_DB": real_audit_store["db"],
            "MENTAT_LOG_PATH": real_audit_store["logs"],
        },
        "chunk_started",
        {"slug": "plan-a"},
    )
    (Path(real_audit_store["logs"]) / repo / agent_id).mkdir(parents=True)
    assert mod.cmd_list() == 0
    out = capsys.readouterr().out
    assert agent_id in out
    assert store.get_agent(agent_id) is not None
