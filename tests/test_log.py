"""Tests for mentat-log skill."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

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
    db = tmp_path / "mentat.db"
    env = {
        "MENTAT_LOG_PATH": str(tmp_path),
        "MENTAT_DB": str(db),
        "MENTAT_SESSION": "s1",
        "MENTAT_REPO": "repo1",
    }
    result = run_log(["emit", "mentat-plan", "plan.started", '{"path":"/tmp/x.md"}'], env=env)
    assert result.returncode == 0, result.stderr
    from lib import store

    rows = store.list_events("s1")
    assert rows, "no events in canonical store"
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


def test_ensure_log_dir_surfaces_chmod_failure(tmp_path, monkeypatch):
    from tests.conftest import load_script

    log = load_script(LOG_SCRIPT, "log_mod")
    log_root = tmp_path / "logs"
    log_root.mkdir()

    def chmod_fail(self, mode):
        raise OSError("chmod denied")

    monkeypatch.setattr(Path, "chmod", chmod_fail)
    with pytest.raises(OSError, match="chmod denied"):
        log._ensure_log_dir(log_root)


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
    db = tmp_path / "mentat.db"
    env = {
        "MENTAT_LOG_PATH": str(tmp_path),
        "MENTAT_DB": str(db),
        "MENTAT_SESSION": "s1",
        "MENTAT_REPO": "repo1",
    }
    run_log(["emit", "mentat-plan", "plan.started", '{"path":"/a.md"}'], env=env)
    run_log(["emit", "mentat-plan", "plan.succeeded", '{"path":"/a.md"}'], env=env)
    result = run_log(["list", "s1", "--event", "plan.started"], env=env)
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert all("plan.started" in ln for ln in lines)
    assert not any("plan.succeeded" in ln for ln in lines)


def test_query_filters_by_agent(tmp_path):
    db = tmp_path / "mentat.db"
    env = {
        "MENTAT_LOG_PATH": str(tmp_path),
        "MENTAT_DB": str(db),
        "MENTAT_SESSION": "s1",
        "MENTAT_REPO": "repo1",
    }
    run_log(["emit", "mentat-plan", "plan.started", '{"path":"/a.md"}'], env=env)
    result = run_log(["list", "s1", "--agent", "mentat-plan"], env=env)
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


def test_session_fallback_is_opaque_uuid(tmp_path, monkeypatch):
    """Unkeyed emit → a real uuid session dir, never an orphan-session-*/pid id."""
    import json as _json
    import re as _re

    monkeypatch.delenv("MENTAT_SESSION", raising=False)
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "plan.started", _json.dumps({"path": "plan.md"}))
    log_mod.cmd_emit(args)

    repo_dir = tmp_path / "test-repo"
    session_dirs = [d for d in repo_dir.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    name = session_dirs[0].name
    assert not name.startswith("orphan-session-"), f"orphan fallback reached: {name!r}"
    assert _re.fullmatch(r"[0-9a-f]{32}", name), f"expected uuid session dir, got {name!r}"


def test_emit_chunk_teardown_accepted(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "test-repo")
    monkeypatch.setenv("MENTAT_SESSION", "sess-123")
    monkeypatch.setenv("MENTAT_SLUG", "test-agent")

    args = _make_emit_args("test-agent", "chunk.teardown", _json.dumps({"slug": "x", "ok": True}))
    rc = log_mod.cmd_emit(args)
    assert rc == 0

    from lib import store

    rows = store.list_events("sess-123")
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
        _json.dumps({"slug": "x", "reason": "implement_failed", "where": "land"}),
    )
    rc = log_mod.cmd_emit(args)
    assert rc == 0, "catalog reason must be accepted"


# ── _validate_row (module-level) ────────────────────────────────────────────


def test_validate_row_missing_top_level_field_reported():
    errs = log_mod._validate_row({"ts": "t", "agent": "a"})
    assert any("missing field" in e for e in errs)


def test_validate_row_unknown_event_reported():
    row = {"ts": "t", "agent": "a", "session": "s", "event": "not.real", "payload": {}}
    errs = log_mod._validate_row(row)
    assert any("unknown event" in e for e in errs)


def test_validate_row_payload_not_dict_reported():
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": [1, 2]}
    errs = log_mod._validate_row(row)
    assert any("payload must be object" in e for e in errs)


def test_validate_row_missing_required_payload_field_reported():
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {}}
    errs = log_mod._validate_row(row)
    assert any("missing required payload field" in e and "'path'" in e for e in errs)


def test_validate_row_valid_row_no_errors():
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {"path": "/x.md"}}
    assert log_mod._validate_row(row) == []


# ── cmd_emit missing branches (module-level) ─────────────────────────────────


def test_emit_unknown_event_returns_rc1(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    monkeypatch.setenv("MENTAT_SESSION", "s-ue")
    args = _make_emit_args("a", "not.a.real.event", _json.dumps({}))
    assert log_mod.cmd_emit(args) == 1


def test_emit_invalid_json_payload_returns_rc1(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    monkeypatch.setenv("MENTAT_SESSION", "s-ij")
    args = _make_emit_args("a", "plan.started", "not-valid-json{{{")
    assert log_mod.cmd_emit(args) == 1


def test_emit_payload_not_dict_returns_rc1(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    monkeypatch.setenv("MENTAT_SESSION", "s-nd")
    args = _make_emit_args("a", "plan.started", _json.dumps([1, 2, 3]))
    assert log_mod.cmd_emit(args) == 1


# ── cmd_validate (module-level) ──────────────────────────────────────────────


def _make_validate_args(file: str) -> _argparse.Namespace:
    ns = _argparse.Namespace()
    ns.file = file
    return ns


def test_validate_file_not_found_returns_rc1(tmp_path):
    args = _make_validate_args(str(tmp_path / "nonexistent.jsonl"))
    assert log_mod.cmd_validate(args) == 1


def test_validate_invalid_json_line_returns_rc1(tmp_path):
    f = tmp_path / "bad.jsonl"
    f.write_text("not-json\n")
    assert log_mod.cmd_validate(_make_validate_args(str(f))) == 1


def test_validate_empty_lines_skipped_returns_0(tmp_path):
    import json as _json

    f = tmp_path / "ok.jsonl"
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {"path": "/x.md"}}
    f.write_text("\n" + _json.dumps(row) + "\n\n")
    assert log_mod.cmd_validate(_make_validate_args(str(f))) == 0


def test_validate_valid_file_returns_0(tmp_path):
    import json as _json

    f = tmp_path / "valid.jsonl"
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {"path": "/x.md"}}
    f.write_text(_json.dumps(row) + "\n")
    assert log_mod.cmd_validate(_make_validate_args(str(f))) == 0


# ── cmd_list (module-level) ──────────────────────────────────────────────────


def _make_list_args(
    agent_id: str,
    event: str | None = None,
    agent: str | None = None,
    *,
    fmt: str = "jsonl",
) -> _argparse.Namespace:
    ns = _argparse.Namespace()
    ns.agent_id = agent_id
    ns.event = event
    ns.agent = agent
    ns.format = fmt
    return ns


def test_query_session_dir_not_found_returns_rc1(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    assert log_mod.cmd_list(_make_list_args("nonexistent-session")) == 1


def test_query_no_filter_returns_all_events(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    monkeypatch.setenv("MENTAT_SESSION", "s-qall")
    monkeypatch.setenv("MENTAT_SLUG", "ag")
    for event, payload in [("plan.started", {"path": "/a.md"}), ("plan.succeeded", {"path": "/a.md"})]:
        args = _make_emit_args("ag", event, _json.dumps(payload))
        log_mod.cmd_emit(args)

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = log_mod.cmd_list(_make_list_args("s-qall"))
    assert rc == 0
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    events = {_json.loads(ln)["event"] for ln in lines}
    assert "plan.started" in events
    assert "plan.succeeded" in events


# ── cmd_prune (module-level) ─────────────────────────────────────────────────


def _make_prune_args(before: str) -> _argparse.Namespace:
    ns = _argparse.Namespace()
    ns.before = before
    return ns


def test_prune_invalid_date_returns_rc1(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    assert log_mod.cmd_prune(_make_prune_args("not-a-date")) == 1


def test_prune_missing_repo_dir_returns_0(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "no-such-repo")
    assert log_mod.cmd_prune(_make_prune_args("2020-01-01")) == 0


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


# ── cmd_validate error-print branch (module-level) ───────────────────────────


def test_validate_row_with_errors_prints_and_returns_rc1(tmp_path):
    import json as _json

    f = tmp_path / "bad.jsonl"
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {}}  # missing path
    f.write_text(_json.dumps(row) + "\n")
    assert log_mod.cmd_validate(_make_validate_args(str(f))) == 1


# ── cmd_list filter branches (module-level) ──────────────────────────────────


def test_query_skips_blank_and_malformed_and_filters(tmp_path, monkeypatch):
    import contextlib
    import io
    import json as _json

    from tests.conftest import seed_agent_events

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    seed_agent_events(
        tmp_path,
        "r",
        "s-qf",
        [
            {"ts": "t1", "event": "plan.started", "payload": {"path": "/a"}},
            {"ts": "t2", "event": "plan.succeeded", "payload": {"path": "/a"}},
        ],
        harness="ag1",
    )

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert log_mod.cmd_list(_make_list_args("s-qf", event="plan.started")) == 0
    events = {_json.loads(ln)["event"] for ln in buf.getvalue().splitlines() if ln.strip()}
    assert events == {"plan.started"}

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        log_mod.cmd_list(_make_list_args("s-qf", agent="ag1"))
    agents = {_json.loads(ln)["agent"] for ln in buf2.getvalue().splitlines() if ln.strip()}
    assert agents == {"ag1"}


# ── cmd_prune real prune loop (module-level) ─────────────────────────────────


def test_prune_removes_old_session_and_skips_files(tmp_path, monkeypatch):
    import datetime as _dt
    import os as _osmod
    import time

    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path))
    monkeypatch.setenv("MENTAT_REPO", "r")
    repo_dir = tmp_path / "r"
    old = repo_dir / "old"
    new = repo_dir / "new"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (repo_dir / "afile").write_text("x")  # non-dir entry → skipped (231-232)
    old_t = time.time() - 10 * 86400
    _osmod.utime(old, (old_t, old_t))
    cutoff = (_dt.date.today() - _dt.timedelta(days=5)).isoformat()
    assert log_mod.cmd_prune(_make_prune_args(cutoff)) == 0
    assert not old.exists()
    assert new.exists()


# ── build_parser + main entrypoint ───────────────────────────────────────────


def test_build_parser_parses_emit_subcommand():
    args = log_mod.build_parser().parse_args(["emit", "ag", "plan.started", "{}"])
    assert args.cmd == "emit"
    assert args.agent == "ag"
    assert args.event == "plan.started"


def test_main_dispatches_to_command(tmp_path, monkeypatch):
    import json as _json

    f = tmp_path / "ok.jsonl"
    row = {"ts": "t", "agent": "a", "session": "s", "event": "plan.started", "payload": {"path": "/x"}}
    f.write_text(_json.dumps(row) + "\n")
    monkeypatch.setattr(log_mod.sys, "argv", ["mentat-log", "validate", str(f)])
    with pytest.raises(SystemExit) as e:
        log_mod.main()
    assert e.value.code == 0


def test_build_parser_parses_list_subcommand():
    args = log_mod.build_parser().parse_args(["list", "agent-1", "--event", "plan.started"])
    assert args.cmd == "list"
    assert args.agent_id == "agent-1"
    assert args.event == "plan.started"
    assert args.format == "jsonl"
