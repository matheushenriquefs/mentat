"""S1: track outside-repo resolves via resolve_agent_dir / resolve_track_repo."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from lib import agent, store  # noqa: E402

from tests.conftest import load_script  # noqa: E402

_TRACK = REPO_ROOT / ".agents/skills/mentat-track/scripts/track.py"


def test_resolve_track_repo_discovers_repo_outside_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    logs = tmp_path / "logs"
    (logs / "myrepo" / "agent-a").mkdir(parents=True)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent, "_repo_root", lambda: None)
    assert agent.resolve_track_repo() == "myrepo"


def test_cmd_track_by_id_outside_repo_without_mentat_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = load_script(_TRACK, "track_fix_s1")
    db = tmp_path / "mentat.db"
    logs = tmp_path / "logs"
    monkeypatch.setenv("MENTAT_DB", str(db))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(logs))
    monkeypatch.delenv("MENTAT_REPO", raising=False)
    monkeypatch.chdir(tmp_path)
    agent_id = "agent-outside-repo"
    store.record_emit(
        {"MENTAT_AGENT": agent_id, "MENTAT_AGENT_PID": str(os.getpid()), "MENTAT_HARNESS": "cursor"},
        "chunk_started",
        {"slug": "x"},
    )
    (logs / "mentat" / agent_id).mkdir(parents=True)
    (logs / "mentat" / agent_id / "transcript.jsonl").write_text(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}) + "\n"
    )
    monkeypatch.setattr(agent, "_repo_root", lambda: None)
    assert mod.cmd_track(agent_id) == 0
    assert "hi" in capsys.readouterr().out
