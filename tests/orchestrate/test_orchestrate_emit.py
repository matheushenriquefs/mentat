"""batch partition emits chunk_ejected into the real store (ADR-0020)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from lib import store  # noqa: E402
from lib.exits import EX_HITL_REQUIRED  # noqa: E402
from tests.conftest import load_script  # noqa: E402


def _batch():
    return load_script(SCRIPTS / "batch.py", "orch_emit_mirror_batch")


def test_hitl_partition_emit_lands_in_real_store(
    real_audit_store: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sched = load_script(SCRIPTS / "scheduler.py", "orch_emit_mirror_sched")
    plan_path = tmp_path / "wedge.md"
    plan_path.write_text("---\nid: wedge\nkind: AFK\n---\n")
    plan = sched.Plan(slug="wedge", kind="AFK", blocked_by=[], path=plan_path)
    batch = _batch()
    monkeypatch.setenv("MENTAT_DB", real_audit_store["db"])
    monkeypatch.setenv("MENTAT_LOG_PATH", real_audit_store["logs"])
    monkeypatch.setenv("MENTAT_AGENT", real_audit_store["agent_id"])
    with (
        patch.object(batch, "_worktree_for_slug", return_value=tmp_path / "wt"),
        patch.object(batch, "_teardown_ejected", lambda slug: None),
    ):
        _chunks, hitl, _transient = batch.partition_by_outcome(
            [(plan, EX_HITL_REQUIRED)],
            mark_ejected=lambda slug: [],
        )
    assert hitl == {"wedge"}
    events = store.list_events(real_audit_store["agent_id"])
    kinds = [e["event"] for e in events]
    assert "chunk_ejected" in kinds
