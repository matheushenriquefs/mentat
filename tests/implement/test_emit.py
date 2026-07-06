"""AFK wedge emits chunk_ejected into the real store (ADR-0020)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"
sys.path.insert(0, str(REPO_ROOT / ".agents"))

from lib import store  # noqa: E402
from tests.conftest import load_script  # noqa: E402


def _impl():
    return load_script(SCRIPTS / "implement.py", "impl_emit_mirror")


def test_wedge_emit_lands_in_real_store(
    real_audit_store: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "afk-wedge.md"
    plan.write_text("---\nid: afk-wedge\nkind: AFK\n---\n# body\n")
    impl = _impl()
    monkeypatch.setenv("MENTAT_DB", real_audit_store["db"])
    monkeypatch.setenv("MENTAT_LOG_PATH", real_audit_store["logs"])
    monkeypatch.setenv("MENTAT_AGENT", real_audit_store["agent_id"])
    with patch.object(impl, "_invoke_harness", return_value=MagicMock(returncode=0)):
        with patch.object(impl, "_read_blocked_summary", return_value="need design call"):
            with patch.object(impl, "_detect_self_answer", return_value=False):
                rc = impl.run_plan(plan, harness="fake")
    assert rc == impl.EX_HITL_REQUIRED
    events = store.list_events(real_audit_store["agent_id"])
    kinds = [e["event"] for e in events]
    assert "chunk_ejected" in kinds
