"""E2E gap-closer: diagnose branches no other session test reaches.

Drives ``diagnose.build_verdict`` / ``build_summary`` over seeded canonical
store rows shaped for branches the report/registry tests miss.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import load_script, seed_agent_events

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
DIAGNOSE_PY = REPO_ROOT / ".agents/skills/mentat-session/scripts/diagnose.py"


def _diagnose():
    return load_script(DIAGNOSE_PY, "e2e_diagnose_gaps")


def _session_dir(tmp_path: Path, agent_id: str) -> Path:
    return tmp_path / "logs" / "repo" / agent_id


def test_build_verdict_no_terminal_event_reports_unknown(tmp_path):
    d = _diagnose()
    agent_id = "session"
    seed_agent_events(
        tmp_path,
        "repo",
        agent_id,
        [
            {"ts": "2026-06-29T00:00:00Z", "event": "plan.started", "payload": {"path": "p.md"}},
            {"ts": "2026-06-29T00:00:01Z", "event": "plan.failed", "payload": {"path": "p.md", "reason": "boom"}},
        ],
    )
    out = d.build_verdict(_session_dir(tmp_path, agent_id))
    assert "- Reason: unknown" in out
    assert "No terminal event found." in out
    assert "plan.failed @ 2026-06-29T00:00:01Z" in out


def test_build_summary_no_terminal_reports_in_session_completion(tmp_path):
    d = _diagnose()
    agent_id = "session"
    seed_agent_events(
        tmp_path,
        "repo",
        agent_id,
        [
            {
                "ts": "2026-06-29T00:00:00Z",
                "event": "chunk.spawned",
                "payload": {"slug": "s1", "plan": "s1.md", "harness": "cc", "worktree": "/wt"},
            },
            {
                "ts": "2026-06-29T00:00:02Z",
                "event": "gate.evaluated",
                "payload": {"gate": "g", "verdict": "pass", "severity": "info", "message": ""},
            },
        ],
    )
    out = d.build_summary(_session_dir(tmp_path, agent_id))
    assert "not yet landed" in out
    assert "- Plan: s1.md" in out
    assert "- Events recorded: 2" in out


def test_build_summary_hitl_eject_appends_operator_blocker(tmp_path):
    d = _diagnose()
    agent_id = "session"
    reason = d.EjectReason.HITL_REQUIRED
    seed_agent_events(
        tmp_path,
        "repo",
        agent_id,
        [
            {
                "ts": "2026-06-29T00:00:00Z",
                "event": "chunk.spawned",
                "payload": {"slug": "s1", "plan": "s1.md", "harness": "cc", "worktree": "/wt"},
            },
            {
                "ts": "2026-06-29T00:00:03Z",
                "event": "chunk.ejected",
                "payload": {"slug": "s1", "reason": reason, "where": "/wt", "summary": "need a schema decision"},
            },
        ],
    )
    out = d.build_summary(_session_dir(tmp_path, agent_id))
    assert "Ejected `s1`" in out
    assert "Blocker: need a schema decision" in out
    assert "diagnosis.md" not in out, "the HITL blocker arm replaces the diagnosis pointer"
