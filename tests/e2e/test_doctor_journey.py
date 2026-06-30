"""E2E: ``mentat-session doctor`` over a real seeded session.

Seed a session under a temp log root whose audit trail ends in a clean ``chunk.landed``,
then run the actual ``mentat-session doctor`` CLI non-interactively. Doctor must exit 0,
print a verdict that reads the landing as a clean finish, and persist ``diagnosis.md``
into the session dir.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

SESSION_PY = Path(__file__).resolve().parents[2] / ".agents/skills/mentat-session/scripts/session.py"


def _seed_landed_session(log_root: Path, repo: str, session_id: str) -> Path:
    """A session whose audit log spawns then lands a chunk — a clean run."""
    sd = log_root / repo / session_id
    sd.mkdir(parents=True)
    events = [
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
    ]
    (sd / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    return sd


def test_doctor_reports_a_clean_landing(tmp_path):
    repo = "doctorrepo"
    log_root = tmp_path / "logs"
    session_id = "orchestrate-main-1"
    sd = _seed_landed_session(log_root, repo, session_id)

    env = {**os.environ, "MENTAT_LOG_PATH": str(log_root), "MENTAT_REPO": repo}
    proc = subprocess.run(
        [sys.executable, str(SESSION_PY), "doctor", session_id],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, f"doctor must exit cleanly:\n{proc.stderr}"
    # Verdict reads the landing as a clean finish.
    assert "Reason: chunk.landed" in proc.stdout, proc.stdout
    assert "chunk landed successfully" in proc.stdout, proc.stdout
    assert "deadbeef" in proc.stdout, "regression section must cite the landed sha"

    # diagnosis.md was persisted into the session dir.
    diagnosis = sd / "diagnosis.md"
    assert diagnosis.exists(), "doctor must write diagnosis.md"
    assert "Reason: chunk.landed" in diagnosis.read_text()
