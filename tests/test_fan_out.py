"""Tests for mentat-orchestrate fan_out module."""

from __future__ import annotations

import importlib.util
import io
from contextlib import redirect_stdout
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


def test_fan_out_prints_track_command_immediately(tmp_path):
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plan = routing.Plan(slug="my-plan", class_="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    fake_session_id = "session-123"

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value=fake_session_id):
        buf = io.StringIO()
        with redirect_stdout(buf):
            session_id = fan_out.spawn(plan)
        output = buf.getvalue()

    # track command printed immediately
    assert "track" in output.lower() or "session" in output.lower()
    assert fake_session_id in output or session_id in output


def test_fan_out_emits_chunk_spawned(tmp_path):
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plan = routing.Plan(slug="my-plan", class_="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value="sess-1"):
        with patch.object(fan_out, "_emit_event") as mock_emit:
            fan_out.spawn(plan)

    emitted_events = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.spawned" in e for e in emitted_events)


def test_fan_out_stdout_emits_chunk_slugs_newline_delim(tmp_path):
    """fan-out debug subcommand prints one slug per line."""
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plans = [
        routing.Plan(slug=f"plan-{i}", class_="AFK", blocked_by=[], path=tmp_path / f"plan-{i}.md")
        for i in range(3)
    ]

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value="sess-x"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            for p in plans:
                fan_out.spawn(p)
        output = buf.getvalue()

    slugs_in_output = [line.strip() for line in output.splitlines() if line.strip()]
    assert len(slugs_in_output) >= 3
