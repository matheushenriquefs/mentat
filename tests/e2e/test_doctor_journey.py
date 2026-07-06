"""E2E: ``mentat-session doctor`` over a real seeded session.

Seed a session whose canonical store ends in a clean ``chunk.landed``,
then run the actual ``mentat-session doctor`` CLI non-interactively.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import seed_agent_events, subprocess_env

pytestmark = pytest.mark.e2e

SESSION_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-session/scripts/session.py"


def test_doctor_reports_a_clean_landing(tmp_path):
    repo = "doctorrepo"
    log_root = tmp_path / "logs"
    session_id = "orchestrate-main-1"
    seed_agent_events(
        tmp_path,
        repo,
        session_id,
        [
            {"ts": "2026-06-30T00:00:00Z", "event": "plan.started", "payload": {"path": "tiny.md"}},
            {
                "ts": "2026-06-30T00:00:01Z",
                "event": "chunk.spawned",
                "payload": {"slug": "tiny", "plan": "tiny.md", "harness": "claude-code", "worktree": "/tmp/wt"},
            },
            {
                "ts": "2026-06-30T00:00:02Z",
                "event": "chunk.landed",
                "payload": {"slug": "tiny", "sha": "deadbeef", "holding": "main"},
            },
        ],
    )
    sd = log_root / repo / session_id
    sd.mkdir(parents=True, exist_ok=True)

    env = subprocess_env(
        MENTAT_LOG_PATH=str(log_root),
        MENTAT_REPO=repo,
        MENTAT_DB=str(tmp_path / "mentat.db"),
    )
    proc = subprocess.run(
        [sys.executable, str(SESSION_PY), "doctor", session_id],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"doctor must exit cleanly:\n{proc.stderr}"
    assert "Reason: chunk.landed" in proc.stdout, proc.stdout
    assert "chunk landed successfully" in proc.stdout, proc.stdout
    assert "deadbeef" in proc.stdout, "regression section must cite the landed sha"
