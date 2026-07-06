"""Tests for agents.py mentat-manual-* filter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from tests.conftest import load_script, seed_agent_events

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-track/scripts"
agents = load_script(SCRIPTS / "registry.py", "registry")


def _ts(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _make_dirs(base: Path, names: list[str]) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for name in names:
        (base / name).mkdir()
    return base


def test_latest_agent_excludes_mentat_manual(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    repo_dir = tmp_path / "logs" / "myrepo"
    _make_dirs(repo_dir, ["mentat-manual-123-456"])
    seed_agent_events(
        tmp_path,
        "myrepo",
        "real-agent",
        [{"ts": _ts(2_000.0), "event": "chunk_landed", "payload": {"slug": "x", "sha": "a", "holding": "h"}}],
    )
    result = agents.latest_agent(repo_dir)
    assert result == "real-agent"


def test_returns_none_when_only_manual_present(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    repo_dir = tmp_path / "logs" / "myrepo"
    _make_dirs(repo_dir, ["mentat-manual-111-222", "mentat-manual-333-444"])
    assert agents.latest_agent(repo_dir) is None


def test_latest_agent_returns_most_recent(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_REPO", "myrepo")
    repo_dir = tmp_path / "logs" / "myrepo"
    seed_agent_events(
        tmp_path,
        "myrepo",
        "agent-a",
        [
            {
                "ts": _ts(1_000.0),
                "event": "gate_evaluated",
                "payload": {"gate": "g", "verdict": "p", "severity": "", "message": ""},
            }
        ],
    )
    seed_agent_events(
        tmp_path,
        "myrepo",
        "agent-b",
        [
            {
                "ts": _ts(2_000.0),
                "event": "gate_evaluated",
                "payload": {"gate": "g", "verdict": "p", "severity": "", "message": ""},
            }
        ],
    )
    assert agents.latest_agent(repo_dir) == "agent-b"
