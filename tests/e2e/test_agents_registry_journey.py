"""E2E: the agents registry helpers over a real seeded ~/.mentat/logs tree.

Exercises the read-side helpers the navigator + kill bind lean on — stream tool
extraction, worktree resolution from the spawn audit, latest-agent selection, age
humanizing, and the attention-ordered ``list_agents`` ranking — against real jsonl
files on disk. In-process so the agents module is measured.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.conftest import load_script, seed_agent_events

pytestmark = pytest.mark.e2e

SESSIONS_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-track/scripts/registry.py"


def _sessions():
    return load_script(SESSIONS_PY, "e2e_sessions")


def _seed(
    agent_dir: Path, *, stream: list[dict] | None = None, events: list[dict] | None = None, age: float = 0.0
) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    if stream is not None:
        (agent_dir / "transcript.jsonl").write_text("".join(json.dumps(r) + "\n" for r in stream))
    if events is not None:
        (agent_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if age:
        old = time.time() - age
        for f in agent_dir.glob("*.jsonl"):
            os.utime(f, (old, old))
        os.utime(agent_dir, (old, old))


def test_agent_stream_tools_extracts_tail(tmp_path):
    ss = _sessions()
    sd = tmp_path / "sess"
    _seed(
        sd,
        stream=[
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        ],
    )
    tools = ss.agent_stream_tools(sd, limit=5)
    assert tools == ["Read", "Bash"]


def test_agent_worktree_from_spawn_audit(tmp_path):
    ss = _sessions()
    agent_id = "sess"
    seed_agent_events(
        tmp_path,
        "repo",
        agent_id,
        [
            {
                "ts": "2026-06-30T00:00:00Z",
                "event": "chunk_started",
                "payload": {"slug": "s", "plan": "s.md", "harness": "claude-code", "worktree": "/wt/one"},
            },
            {
                "ts": "2026-06-30T00:00:01Z",
                "event": "chunk_started",
                "payload": {"slug": "s", "plan": "s.md", "harness": "claude-code", "worktree": "/wt/two"},
            },
        ],
    )
    sd = tmp_path / "logs" / "repo" / agent_id
    sd.mkdir(parents=True, exist_ok=True)
    assert ss.agent_worktree(sd) == "/wt/two", "latest spawn's worktree wins"


def test_agent_worktree_none_without_spawn(tmp_path):
    ss = _sessions()
    agent_id = "sess"
    seed_agent_events(
        tmp_path,
        "repo",
        agent_id,
        [{"ts": "2026-06-30T00:00:00Z", "event": "chunk_started", "payload": {"path": "p.md"}}],
    )
    sd = tmp_path / "logs" / "repo" / agent_id
    sd.mkdir(parents=True, exist_ok=True)
    assert ss.agent_worktree(sd) is None


def test_latest_agent_picks_newest_dir(tmp_path, monkeypatch):
    ss = _sessions()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    repo_dir = tmp_path / "logs" / "repo"
    seed_agent_events(
        tmp_path,
        "repo",
        "old",
        [{"ts": "2026-01-01T00:00:00Z", "event": "chunk_started", "payload": {"path": "p"}}],
    )
    seed_agent_events(
        tmp_path,
        "repo",
        "new",
        [{"ts": "2026-07-01T00:00:00Z", "event": "chunk_started", "payload": {"path": "p"}}],
    )
    (repo_dir / "old").mkdir(parents=True, exist_ok=True)
    (repo_dir / "new").mkdir(parents=True, exist_ok=True)
    _seed(repo_dir / "mentat-manual-x", events=[{"ts": "t", "event": "chunk_started", "payload": {"path": "p"}}])
    assert ss.latest_agent(repo_dir) == "new"


def test_latest_agent_empty_repo_is_none(tmp_path):
    ss = _sessions()
    repo_dir = tmp_path / "empty"
    repo_dir.mkdir()
    assert ss.latest_agent(repo_dir) is None


def test_humanize_age_buckets(tmp_path):
    ss = _sessions()
    assert ss._humanize_age(5) == "5s ago"
    assert ss._humanize_age(120) == "2m ago"
    assert ss._humanize_age(7200) == "2h ago"
    assert ss._humanize_age(172800) == "2d ago"


def test_list_agents_ranks_attention_to_top(tmp_path, monkeypatch):
    ss = _sessions()
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    monkeypatch.setenv("MENTAT_REPO", "repo")
    repo_dir = tmp_path / "logs" / "repo"
    seed_agent_events(
        tmp_path,
        "repo",
        "waiter",
        [
            {
                "event": "chunk_ejected",
                "payload": {"slug": "s", "reason": "hitl_required", "where": "/wt"},
            },
        ],
        status="running",
    )
    (repo_dir / "waiter").mkdir(parents=True, exist_ok=True)
    seed_agent_events(
        tmp_path,
        "repo",
        "done",
        [
            {
                "ts": "2026-06-30T00:00:00Z",
                "event": "chunk_landed",
                "payload": {"slug": "s", "sha": "x", "holding": "main"},
            },
        ],
    )
    (repo_dir / "done").mkdir(parents=True, exist_ok=True)
    records = ss.list_agents(repo_dir, active_only=False)
    order = [r["agent"] for r in records]
    assert order.index("waiter") < order.index("done"), "waiting floats above idle"
    statuses = {r["agent"]: r["status"] for r in records}
    assert statuses["waiter"] == "waiting"
    assert statuses["done"] == "idle"


def test_list_agents_missing_repo_is_empty(tmp_path):
    ss = _sessions()
    assert ss.list_agents(tmp_path / "nope", active_only=True) == []
