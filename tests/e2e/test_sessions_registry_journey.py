"""E2E: the sessions registry helpers over a real seeded ~/.mentat/logs tree.

Exercises the read-side helpers the navigator + kill bind lean on — stream tool
extraction, worktree resolution from the spawn audit, latest-session selection, age
humanizing, and the attention-ordered ``list_sessions`` ranking — against real jsonl
files on disk. In-process so the sessions module is measured.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

SESSIONS_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-session/scripts/sessions.py"


def _sessions():
    return load_script(SESSIONS_PY, "e2e_sessions")


def _seed(
    session_dir: Path, *, stream: list[dict] | None = None, events: list[dict] | None = None, age: float = 0.0
) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    if stream is not None:
        (session_dir / "session.jsonl").write_text("".join(json.dumps(r) + "\n" for r in stream))
    if events is not None:
        (session_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if age:
        old = time.time() - age
        for f in session_dir.glob("*.jsonl"):
            os.utime(f, (old, old))
        os.utime(session_dir, (old, old))


def test_session_stream_tools_extracts_tail(tmp_path):
    ss = _sessions()
    sd = tmp_path / "sess"
    _seed(
        sd,
        stream=[
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
        ],
    )
    tools = ss.session_stream_tools(sd, limit=5)
    assert tools == ["Read", "Bash"]


def test_session_worktree_from_spawn_audit(tmp_path):
    ss = _sessions()
    sd = tmp_path / "sess"
    _seed(
        sd,
        events=[
            {
                "ts": "2026-06-30T00:00:00Z",
                "event": "chunk.spawned",
                "payload": {"slug": "s", "plan": "s.md", "harness": "claude-code", "worktree": "/wt/one"},
            },
            {
                "ts": "2026-06-30T00:00:01Z",
                "event": "chunk.spawned",
                "payload": {"slug": "s", "plan": "s.md", "harness": "claude-code", "worktree": "/wt/two"},
            },
        ],
    )
    assert ss.session_worktree(sd) == "/wt/two", "latest spawn's worktree wins"


def test_session_worktree_none_without_spawn(tmp_path):
    ss = _sessions()
    sd = tmp_path / "sess"
    _seed(sd, events=[{"ts": "2026-06-30T00:00:00Z", "event": "plan.started", "payload": {"path": "p.md"}}])
    assert ss.session_worktree(sd) is None


def test_latest_session_picks_newest_dir(tmp_path):
    ss = _sessions()
    repo_dir = tmp_path / "repo"
    _seed(repo_dir / "old", events=[{"ts": "t", "event": "plan.started", "payload": {"path": "p"}}], age=600)
    _seed(repo_dir / "new", events=[{"ts": "t", "event": "plan.started", "payload": {"path": "p"}}])
    # mentat-manual-* sessions are excluded from the "latest" pick.
    _seed(repo_dir / "mentat-manual-x", events=[{"ts": "t", "event": "plan.started", "payload": {"path": "p"}}])
    assert ss.latest_session(repo_dir) == "new"


def test_latest_session_empty_repo_is_none(tmp_path):
    ss = _sessions()
    repo_dir = tmp_path / "empty"
    repo_dir.mkdir()
    assert ss.latest_session(repo_dir) is None


def test_humanize_age_buckets(tmp_path):
    ss = _sessions()
    assert ss._humanize_age(5) == "5s ago"
    assert ss._humanize_age(120) == "2m ago"
    assert ss._humanize_age(7200) == "2h ago"
    assert ss._humanize_age(172800) == "2d ago"


def test_chunks_and_sessions_listing(tmp_path):
    ss = _sessions()
    repo_dir = tmp_path / "repo"
    _seed(repo_dir / "a", stream=[{"type": "assistant", "message": {"content": []}}])
    _seed(repo_dir / "mentat-manual-b", stream=[{"type": "assistant", "message": {"content": []}}])
    names = ss.sessions_for_repo(repo_dir)
    assert "a" in names
    assert "mentat-manual-b" not in names, "ad-hoc manual runs are excluded"

    chunks = ss.chunks_in_session(repo_dir / "a")
    assert [p.name for p in chunks] == ["session.jsonl"]


def test_list_sessions_ranks_attention_to_top(tmp_path):
    ss = _sessions()
    repo_dir = tmp_path / "repo"
    # waiting (AskUserQuestion, fresh) must outrank an idle landed session.
    _seed(
        repo_dir / "waiter",
        stream=[
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "AskUserQuestion", "input": {}}]},
            },
        ],
    )
    _seed(
        repo_dir / "done",
        events=[
            {
                "ts": "2026-06-30T00:00:00Z",
                "event": "chunk.landed",
                "payload": {"slug": "s", "sha": "x", "holding": "main"},
            },
        ],
    )
    records = ss.list_sessions(repo_dir, active_only=False)
    order = [r["session"] for r in records]
    assert order.index("waiter") < order.index("done"), "waiting floats above idle"
    statuses = {r["session"]: r["status"] for r in records}
    assert statuses["waiter"] == "waiting"
    assert statuses["done"] == "idle"


def test_list_sessions_missing_repo_is_empty(tmp_path):
    ss = _sessions()
    assert ss.list_sessions(tmp_path / "nope", active_only=True) == []
