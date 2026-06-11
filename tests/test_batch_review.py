"""Tests for mentat-orchestrate batch_review module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_batch_review_advisory_emits_batch_reviewed():
    fr = load_module("batch_review")

    with patch.object(fr, "_emit_event") as mock_emit:
        fr.review(session_id="sess-1")

    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("batch.reviewed" in e for e in emitted)
