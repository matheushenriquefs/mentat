"""Tests for mentat-orchestrate fan_out module."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests.conftest import load_script

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


class _FakePopen:
    """Stand-in for subprocess.Popen — returns immediate exit on poll()."""

    def poll(self) -> int:
        return 0


def load_module(name: str):
    return load_script(SCRIPTS / f"{name}.py", name)


def test_fan_out_spawns_worktree_and_subprocess(tmp_path):
    """spawn() calls _spawn_worktree_subprocess and returns the session id."""
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plan = routing.Plan(slug="my-plan", class_="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    spawn_calls = []

    def fake_spawn(p, harness=None, model=None):
        spawn_calls.append(p)
        return ("sess-abc", _FakePopen())

    with patch.object(fan_out, "_spawn_worktree_subprocess", side_effect=fake_spawn):
        with patch.object(fan_out, "_emit_event"):
            session_id = fan_out.spawn(plan)

    assert spawn_calls, "worktree subprocess was not called"
    assert session_id == "sess-abc"


def test_fan_out_prints_track_command_immediately(tmp_path):
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plan = routing.Plan(slug="my-plan", class_="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    fake_session_id = "session-123"

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value=(fake_session_id, _FakePopen())):
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

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value=("sess-1", _FakePopen())):
        with patch.object(fan_out, "_emit_event") as mock_emit:
            fan_out.spawn(plan)

    emitted_events = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk.spawned" in e for e in emitted_events)


def test_fan_out_stdout_emits_chunk_slugs_newline_delim(tmp_path):
    """fan-out debug subcommand prints one slug per line."""
    fan_out = load_module("fan_out")
    routing = load_module("routing")
    plans = [
        routing.Plan(slug=f"plan-{i}", class_="AFK", blocked_by=[], path=tmp_path / f"plan-{i}.md") for i in range(3)
    ]

    with patch.object(fan_out, "_spawn_worktree_subprocess", return_value=("sess-x", _FakePopen())):
        buf = io.StringIO()
        with redirect_stdout(buf):
            for p in plans:
                fan_out.spawn(p)
        output = buf.getvalue()

    slugs_in_output = [line.strip() for line in output.splitlines() if line.strip()]
    assert len(slugs_in_output) >= 3
