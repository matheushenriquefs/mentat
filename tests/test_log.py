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
    """Pin: exactly 9 canonical events with exact names from plan §A."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("log", LOG_SCRIPT)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    catalog = mod.EVENT_CATALOG
    expected = {
        "plan.started",
        "plan.succeeded",
        "plan.failed",
        "chunk.spawned",
        "chunk.landed",
        "chunk.ejected",
        "gate.evaluated",
        "review.submitted",
        "batch.reviewed",
    }
    assert set(catalog.keys()) == expected, (
        f"catalog mismatch. extra={set(catalog) - expected} missing={expected - set(catalog)}"
    )
    assert len(catalog) == 9
