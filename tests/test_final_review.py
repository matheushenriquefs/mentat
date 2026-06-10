"""Tests for mentat-orchestrate final_review module."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def load_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_final_review_advisory_emits_batch_reviewed():
    fr = load_module("final_review")

    with patch.object(fr, "_emit_event") as mock_emit:
        fr.review(session_id="sess-1")

    emitted = [c.args[0] for c in mock_emit.call_args_list]
    assert any("batch.reviewed" in e for e in emitted)
