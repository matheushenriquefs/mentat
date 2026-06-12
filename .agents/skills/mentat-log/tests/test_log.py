"""Tests for mentat-log fallback id naming."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import log as log_mod


def test_agent_slug_fallback_is_mentat_manual(monkeypatch):
    monkeypatch.delenv("MENTAT_SLUG", raising=False)
    slug = log_mod._agent_slug()
    assert slug.startswith("mentat-manual-"), f"expected mentat-manual- prefix, got {slug!r}"
    assert slug == f"mentat-manual-{os.getpid()}"


def test_explicit_slug_overrides_fallback(monkeypatch):
    monkeypatch.setenv("MENTAT_SLUG", "my-custom-slug")
    assert log_mod._agent_slug() == "my-custom-slug"


def test_session_fallback_is_mentat_manual(tmp_path, monkeypatch):
    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "plan.started", json.dumps({"path": "plan.md"}))
    log_mod.cmd_emit(args)

    repo_dir = tmp_path / "test-repo"
    session_dirs = [d for d in repo_dir.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    assert session_dirs[0].name.startswith("mentat-manual-"), (
        f"expected mentat-manual- prefix, got {session_dirs[0].name!r}"
    )


def test_emit_chunk_teardown_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-123")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "chunk.teardown", json.dumps({"slug": "x", "ok": True}))
    rc = log_mod.cmd_emit(args)
    assert rc == 0

    session_dir = tmp_path / "test-repo" / "sess-123"
    log_files = list(session_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    rows = [json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["event"] == "chunk.teardown"
    assert rows[0]["payload"] == {"slug": "x", "ok": True}


def test_chunk_teardown_missing_slug_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-456")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "chunk.teardown", json.dumps({}))
    rc = log_mod.cmd_emit(args)
    assert rc == 1

    sidecar = tmp_path / "test-repo" / "sess-456" / ".stderr" / "test-agent-test-agent.stderr"
    assert sidecar.exists()
    content = sidecar.read_text()
    assert "chunk.teardown" in content


def _make_emit_args(agent: str, event: str, payload: str):
    import argparse

    ns = argparse.Namespace()
    ns.agent = agent
    ns.event = event
    ns.payload = payload
    return ns
