"""S4: real_audit_store conftest fixture per ADR-0020."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_SCRIPT = REPO_ROOT / ".agents/skills/mentat-log/scripts/log.py"


def _run_log(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(LOG_SCRIPT), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_real_audit_store_round_trips_emit(real_audit_store: dict[str, str]) -> None:
    from lib import store

    env = {
        "MENTAT_AGENT": real_audit_store["agent_id"],
        "MENTAT_HARNESS": "test",
        "MENTAT_DB": real_audit_store["db"],
        "MENTAT_LOG_PATH": real_audit_store["logs"],
    }
    result = _run_log(
        [
            "emit",
            "mentat-foundation",
            "agent_started",
            '{"harness":"test"}',
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    rows = store.list_events(real_audit_store["agent_id"])
    assert rows, "emit did not land in sqlite store"
    assert rows[-1]["event"] == "agent_started"
    assert rows[-1]["payload"]["harness"] == "test"


def test_real_audit_store_rejects_uncataloged_emit(real_audit_store: dict[str, str]) -> None:
    from lib import store

    env = {
        "MENTAT_AGENT": real_audit_store["agent_id"],
        "MENTAT_HARNESS": "test",
        "MENTAT_DB": real_audit_store["db"],
        "MENTAT_LOG_PATH": real_audit_store["logs"],
    }
    before = len(store.list_events(real_audit_store["agent_id"]))
    result = _run_log(
        [
            "emit",
            "mentat-foundation",
            "chunk_spawned",
            '{"slug":"x","plan":"p","harness":"h","worktree":"/w"}',
        ],
        env=env,
    )
    assert result.returncode != 0
    assert "unknown event" in result.stderr.lower()
    after = len(store.list_events(real_audit_store["agent_id"]))
    assert after == before, "uncataloged emit must not append a row"
