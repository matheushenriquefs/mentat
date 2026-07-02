"""E2E gap-closer: doctor branches no other session test reaches.

Drives ``doctor.build_verdict`` / ``build_summary`` over real session dirs (a
jsonl of audit rows on tmp) shaped for the branches the report/registry tests
miss: a session with events but *no* terminal chunk.landed/ejected (the
"no terminal event" verdict + the "completed, not yet landed" summary), and a
HITL-required ejection carrying an operator blocker (the summary's Blocker
arm). In-process — no subprocess, no docker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import load_script

pytestmark = pytest.mark.e2e

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PY = REPO_ROOT / ".agents/skills/mentat-session/scripts/doctor.py"


def _doctor():
    return load_script(DOCTOR_PY, "e2e_doctor_gaps")


def _session_dir(tmp_path: Path, rows: list[dict]) -> Path:
    """Write one audit jsonl into a fresh session dir and return the dir."""
    sd = tmp_path / "session"
    sd.mkdir()
    lines = "\n".join(json.dumps(r) for r in rows) + "\n"
    (sd / "agent-chunk.jsonl").write_text(lines)
    return sd


# ── build_verdict: events present but no terminal event ───────────────────────
# doctor.py 40->45 + 41->40 (the reversed scan exhausts without a terminal) and
# 64-65 (the else arm → reason "unknown" / "No terminal event found.").


def test_build_verdict_no_terminal_event_reports_unknown(tmp_path):
    d = _doctor()
    # A started plan then a failure — a real first-failed row, but neither
    # chunk.landed nor chunk.ejected ever fires, so the terminal scan whiffs.
    sd = _session_dir(
        tmp_path,
        [
            {"ts": "2026-06-29T00:00:00Z", "event": "plan.started", "payload": {"path": "p.md"}},
            {"ts": "2026-06-29T00:00:01Z", "event": "plan.failed", "payload": {"path": "p.md", "reason": "boom"}},
        ],
    )
    out = d.build_verdict(sd)
    assert "- Reason: unknown" in out
    assert "No terminal event found." in out
    # first_failed still resolves off the plan.failed row.
    assert "plan.failed @ 2026-06-29T00:00:01Z" in out


# ── build_summary: no terminal → "completed, not yet landed" (125->130, 145) ──


def test_build_summary_no_terminal_reports_in_session_completion(tmp_path):
    d = _doctor()
    sd = _session_dir(
        tmp_path,
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
    out = d.build_summary(sd)
    assert "not yet landed" in out
    assert "- Plan: s1.md" in out
    assert "- Events recorded: 2" in out


# ── build_summary: HITL-required eject with a blocker → the Blocker arm (141) ──


def test_build_summary_hitl_eject_appends_operator_blocker(tmp_path):
    d = _doctor()
    reason = d.EjectReason.HITL_REQUIRED
    sd = _session_dir(
        tmp_path,
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
    out = d.build_summary(sd)
    assert "Ejected `s1`" in out
    assert "Blocker: need a schema decision" in out
    assert "diagnosis.md" not in out, "the HITL blocker arm replaces the diagnosis pointer"
