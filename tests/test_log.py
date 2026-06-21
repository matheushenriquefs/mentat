"""Tests for mentat-log skill."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

LOG_SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-log/scripts/log.py"


def run_log(args: list[str], env: dict | None = None, input: str | None = None):
    import subprocess

    full_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["python3", str(LOG_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=full_env,
        input=input,
    )


# ── B1 tests ────────────────────────────────────────────────────────────────


def test_emit_appends_jsonl(tmp_path):
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    result = run_log(["emit", "mentat-plan", "plan.started", '{"path":"/tmp/x.md"}'], env=env)
    assert result.returncode == 0, result.stderr
    files = list(tmp_path.rglob("*.jsonl"))
    assert files, "no jsonl written"
    rows = [json.loads(ln) for ln in files[0].read_text().splitlines() if ln.strip()]
    assert rows[0]["event"] == "plan.started"
    assert rows[0]["payload"]["path"] == "/tmp/x.md"


def test_emit_unknown_event_rejected(tmp_path):
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    result = run_log(["emit", "mentat-plan", "plan.nonexistent", '{"path":"/tmp/x.md"}'], env=env)
    assert result.returncode != 0
    assert "unknown event" in result.stderr.lower() or "unknown" in result.stderr.lower()


def test_emit_missing_required_field_routes_to_sidecar(tmp_path):
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    # plan.started requires "path"
    result = run_log(["emit", "mentat-plan", "plan.started", "{}"], env=env)
    assert result.returncode != 0
    sidecar_files = list(tmp_path.rglob("*.stderr"))
    assert sidecar_files, "no sidecar written"


def test_emit_creates_log_dir_0700(tmp_path):
    log_root = tmp_path / "logs"
    env = {"MENTAT_LOG_PATH": str(log_root), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    result = run_log(["emit", "mentat-plan", "plan.started", '{"path":"/tmp/x.md"}'], env=env)
    assert result.returncode == 0, result.stderr
    mode = oct(stat.S_IMODE(log_root.stat().st_mode))
    assert mode == oct(0o700), f"expected 0o700, got {mode}"


def test_validate_catches_missing_field(tmp_path):
    # Write a JSONL with a missing required field
    bad_row = json.dumps(
        {
            "ts": "2026-01-01T00:00:00+00:00",
            "agent": "mentat-plan",
            "session": "s1",
            "event": "plan.started",
            "payload": {},  # missing "path"
        }
    )
    log_file = tmp_path / "test.jsonl"
    log_file.write_text(bad_row + "\n")
    result = run_log(["validate", str(log_file)])
    assert result.returncode != 0


def test_query_filters_by_event(tmp_path):
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    run_log(["emit", "mentat-plan", "plan.started", '{"path":"/a.md"}'], env=env)
    run_log(["emit", "mentat-plan", "plan.succeeded", '{"path":"/a.md"}'], env=env)
    result = run_log(["query", "s1", "--event", "plan.started"], env=env)
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert all("plan.started" in ln for ln in lines)
    assert not any("plan.succeeded" in ln for ln in lines)


def test_query_filters_by_agent(tmp_path):
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_SESSION": "s1", "MENTAT_REPO": "repo1"}
    run_log(["emit", "mentat-plan", "plan.started", '{"path":"/a.md"}'], env=env)
    run_log(["emit", "mentat-implement", "plan.started", '{"path":"/a.md"}'], env=env)
    result = run_log(["query", "s1", "--agent", "mentat-plan"], env=env)
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    for line in lines:
        row = json.loads(line)
        assert row["agent"] == "mentat-plan"


def test_prune_drops_old_dirs(tmp_path):
    import time

    repo_dir = tmp_path / "repo1"
    old_session = repo_dir / "old-session"
    new_session = repo_dir / "new-session"
    old_session.mkdir(parents=True)
    new_session.mkdir(parents=True)
    # Set old_session mtime to 10 days ago
    old_time = time.time() - 10 * 86400
    os.utime(old_session, (old_time, old_time))
    env = {"MENTAT_LOG_PATH": str(tmp_path), "MENTAT_REPO": "repo1"}
    # Prune sessions older than 5 days
    import datetime

    cutoff = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    result = run_log(["prune", "--before", cutoff], env=env)
    assert result.returncode == 0, result.stderr
    assert not old_session.exists(), "old session not pruned"
    assert new_session.exists(), "new session wrongly pruned"


def test_event_catalog_matches_parent_plan():
    """Pin: exactly 16 canonical events with exact names from ADR-0007 v5."""
    from tests.conftest import load_script

    mod = load_script(LOG_SCRIPT, "log")
    catalog = mod.EVENT_CATALOG
    expected = {
        "plan.started",
        "plan.succeeded",
        "plan.failed",
        "chunk.spawned",
        "chunk.landed",
        "chunk.ejected",
        "chunk.teardown",
        "gate.evaluated",
        "review.submitted",
        "batch.reviewed",
        "task.created",
        "task.claimed",
        "task.released",
        "task.done",
        "task.wontfix",
        "session.prune",
    }
    assert set(catalog.keys()) == expected, (
        f"catalog mismatch. extra={set(catalog) - expected} missing={expected - set(catalog)}"
    )
    assert len(catalog) == 16


# ── log module-API tests ─────────────────────────────────────────────────────

import argparse as _argparse  # noqa: E402
import os as _os  # noqa: E402

import log as log_mod  # noqa: E402


def _make_emit_args(agent: str, event: str, payload: str):
    ns = _argparse.Namespace()
    ns.agent = agent
    ns.event = event
    ns.payload = payload
    return ns


def test_agent_slug_fallback_is_mentat_manual(monkeypatch):
    monkeypatch.delenv("MENTAT_SLUG", raising=False)
    slug = log_mod._agent_slug()
    assert slug.startswith("agent-"), f"expected agent- prefix, got {slug!r}"
    assert slug == f"agent-{_os.getpid()}"


def test_explicit_slug_overrides_fallback(monkeypatch):
    monkeypatch.setenv("MENTAT_SLUG", "my-custom-slug")
    assert log_mod._agent_slug() == "my-custom-slug"


def test_session_fallback_is_mentat_manual(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "plan.started", _json.dumps({"path": "plan.md"}))
    log_mod.cmd_emit(args)

    repo_dir = tmp_path / "test-repo"
    session_dirs = [d for d in repo_dir.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    assert session_dirs[0].name.startswith("orphan-session-"), (
        f"expected orphan-session- prefix, got {session_dirs[0].name!r}"
    )


def test_emit_chunk_teardown_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-123")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "chunk.teardown", _json.dumps({"slug": "x", "ok": True}))
    rc = log_mod.cmd_emit(args)
    assert rc == 0

    session_dir = tmp_path / "test-repo" / "sess-123"
    log_files = list(session_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    rows = [_json.loads(line) for line in log_files[0].read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["event"] == "chunk.teardown"
    assert rows[0]["payload"] == {"slug": "x", "ok": True}


def test_chunk_teardown_missing_slug_rejected(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-456")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "chunk.teardown", _json.dumps({}))
    rc = log_mod.cmd_emit(args)
    assert rc == 1

    sidecar = tmp_path / "test-repo" / "sess-456" / ".stderr" / "test-agent-test-agent.stderr"
    assert sidecar.exists()
    content = sidecar.read_text()
    assert "chunk.teardown" in content


def test_emit_task_created_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-tc1")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "task.created", _json.dumps({"id": "T001", "slug": "x"}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_task_claimed_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-tc2")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args(
        "test-agent",
        "task.claimed",
        _json.dumps({"id": "T001", "agent": "a", "expires_at": "2026-06-12T00:00:00Z"}),
    )
    assert log_mod.cmd_emit(args) == 0


def test_emit_task_released_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-tc3")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "task.released", _json.dumps({"id": "T001"}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_task_done_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-tc4")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "task.done", _json.dumps({"id": "T001"}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_task_wontfix_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-tc5")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "task.wontfix", _json.dumps({"id": "T001"}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_session_prune_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-sp1")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "session.prune", _json.dumps({"reclaimed_bytes": 12345}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_session_prune_null_bytes_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-sp2")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args("test-agent", "session.prune", _json.dumps({"reclaimed_bytes": None}))
    assert log_mod.cmd_emit(args) == 0


def test_emit_chunk_ejected_unknown_reason_rejected(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-lt1-bad")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args(
        "test-agent",
        "chunk.ejected",
        _json.dumps({"slug": "x", "reason": "not-a-real-reason", "where": "land"}),
    )
    rc = log_mod.cmd_emit(args)
    assert rc == 1, "expected rejection for unknown eject reason"


def test_emit_chunk_ejected_catalog_reason_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-lt1-good")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")
    args = _make_emit_args(
        "test-agent",
        "chunk.ejected",
        _json.dumps({"slug": "x", "reason": "implement-failed", "where": "land"}),
    )
    rc = log_mod.cmd_emit(args)
    assert rc == 0, "catalog reason must be accepted"


def test_emit_missing_required_key_rejected(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    cases = [
        ("task.created", {"slug": "x"}),
        ("task.created", {"id": "T001"}),
        ("task.claimed", {"id": "T001", "agent": "a"}),
        ("task.released", {}),
        ("task.done", {}),
        ("task.wontfix", {}),
        ("session.prune", {}),
    ]
    for i, (event, payload) in enumerate(cases):
        monkeypatch.setenv("MENTAT_SESSION", f"sess-rej-{i}")
        args = _make_emit_args("test-agent", event, _json.dumps(payload))
        rc = log_mod.cmd_emit(args)
        assert rc == 1, f"expected rc=1 for {event} with payload {payload}, got {rc}"
        sidecar = tmp_path / "test-repo" / f"sess-rej-{i}" / ".stderr" / "test-agent-test-agent.stderr"
        assert sidecar.exists(), f"sidecar not written for {event}"
