"""Tests for mentat-orchestrate spawn module."""

from __future__ import annotations

import asyncio
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
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="my-plan", kind="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    spawn_calls = []

    def fake_spawn(p, harness=None, model=None, seed_summary=None):
        spawn_calls.append(p)
        return ("sess-abc", _FakePopen(), tmp_path / "wt")

    with patch.object(spawn, "_spawn_worktree_subprocess", side_effect=fake_spawn):
        with patch.object(spawn, "_emit_event"):
            session_id = spawn.spawn(plan)

    assert spawn_calls, "worktree subprocess was not called"
    assert session_id == "sess-abc"


def test_fan_out_prints_track_command_immediately(tmp_path):
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="my-plan", kind="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    fake_session_id = "session-123"

    with patch.object(
        spawn, "_spawn_worktree_subprocess", return_value=(fake_session_id, _FakePopen(), tmp_path / "wt")
    ):
        buf = io.StringIO()
        with redirect_stdout(buf):
            session_id = spawn.spawn(plan)
        output = buf.getvalue()

    # track command printed immediately
    assert "track" in output.lower() or "session" in output.lower()
    assert fake_session_id in output or session_id in output


def test_fan_out_emits_chunk_spawned(tmp_path):
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="my-plan", kind="AFK", blocked_by=[], path=tmp_path / "my-plan.md")

    with patch.object(spawn, "_spawn_worktree_subprocess", return_value=("sess-1", _FakePopen(), tmp_path / "wt")):
        with patch.object(spawn, "_emit_event") as mock_emit:
            spawn.spawn(plan)

    emitted_events = [c.args[0] for c in mock_emit.call_args_list]
    assert any("chunk_started" in e for e in emitted_events)


def test_fan_out_stdout_emits_chunk_slugs_newline_delim(tmp_path):
    """fan-out debug subcommand prints one slug per line."""
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plans = [
        routing.Plan(slug=f"plan-{i}", kind="AFK", blocked_by=[], path=tmp_path / f"plan-{i}.md") for i in range(3)
    ]

    with patch.object(spawn, "_spawn_worktree_subprocess", return_value=("sess-x", _FakePopen(), tmp_path / "wt")):
        buf = io.StringIO()
        with redirect_stdout(buf):
            for p in plans:
                spawn.spawn(p)
        output = buf.getvalue()

    slugs_in_output = [line.strip() for line in output.splitlines() if line.strip()]
    assert len(slugs_in_output) >= 3


# ── B3: track suggestion must be bin form, not python3 path ───────────────────


def test_fan_out_track_suggestion_is_bin_form(tmp_path):
    """spawn_with_proc must print `mentat-track track <id>`, never `python3 ...`."""
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="p", kind="AFK", blocked_by=[], path=tmp_path / "p.md")

    with patch.object(
        spawn, "_spawn_worktree_subprocess", return_value=("sess-binform", _FakePopen(), tmp_path / "wt")
    ):
        with patch.object(spawn, "_emit_event", lambda *a, **k: None):
            buf = io.StringIO()
            with redirect_stdout(buf):
                spawn.spawn_with_proc(plan)
            output = buf.getvalue()

    assert "python3" not in output, f"bin form must not contain python3: {output!r}"
    assert "mentat-track track" in output, f"must use bin form; got: {output!r}"
    assert "sess-binform" in output, f"session id missing from track output: {output!r}"


# ── spawn_async: asyncio supervisor spawn path ──────────────────────────────


def test_spawn_async_emits_prints_and_returns_process(tmp_path, monkeypatch):
    """spawn_async builds the child via _build_spawn_cmd, launches it with
    asyncio.create_subprocess_exec (start_new_session=True), emits chunk_started,
    prints the track command, and returns (session_id, Process) (spawn.py:123-131)."""
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="async-plan", kind="AFK", blocked_by=[], path=tmp_path / "async-plan.md")

    fake_proc = object()
    captured: dict[str, object] = {}

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = cmd
        captured["new_group"] = kwargs.get(spawn._POPEN_NEW_GROUP)
        return fake_proc

    monkeypatch.setattr(
        spawn, "_prepare_chunk_spawn", lambda plan, **kw: ("sess-async", ["python3", "impl"], {}, tmp_path / "wt")
    )
    monkeypatch.setattr(spawn.asyncio, "create_subprocess_exec", fake_exec)

    with patch.object(spawn, "_emit_event") as mock_emit:
        buf = io.StringIO()
        with redirect_stdout(buf):
            sid, proc, _wt = asyncio.run(spawn.spawn_async(plan))
        output = buf.getvalue()

    assert sid == "sess-async"
    assert proc is fake_proc
    assert captured["new_group"] is True
    assert any("chunk_started" in c.args[0] for c in mock_emit.call_args_list)
    assert "mentat-track track sess-async" in output
    assert "sess-async" in output


# ── _spawn_worktree_subprocess: harness/model/seed argv + env wiring ─────────


def test_spawn_worktree_subprocess_wires_harness_model_and_seed(tmp_path, monkeypatch):
    """harness/model append CLI flags; seed_summary injects MENTAT_SEED_SUMMARY."""
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="wire", kind="AFK", blocked_by=[], path=tmp_path / "p.md")

    monkeypatch.setattr(
        spawn,
        "_prepare_chunk_spawn",
        lambda p, **kw: (
            "sess-wire",
            ["python3", "impl", "--harness", "cursor", "--model", "opus"],
            {"MENTAT_AGENT": "sess-wire", "MENTAT_SEED_SUMMARY": "prior ctx", "MENTAT_CHUNK_ID": "c" * 32},
            tmp_path / "wt",
        ),
    )

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        captured["new_group"] = kwargs.get(spawn._POPEN_NEW_GROUP)
        captured["cwd"] = kwargs.get("cwd")
        return _FakePopen()

    monkeypatch.setattr(spawn.subprocess, "Popen", fake_popen)

    sid, proc, wt = spawn._spawn_worktree_subprocess(plan, harness="cursor", model="opus", seed_summary="prior ctx")

    assert sid == "sess-wire"
    assert wt == tmp_path / "wt"
    cmd = captured["cmd"]
    assert "--harness" in cmd and cmd[cmd.index("--harness") + 1] == "cursor"
    assert "--model" in cmd and cmd[cmd.index("--model") + 1] == "opus"
    env = captured["env"]
    assert env["MENTAT_AGENT"] == "sess-wire"
    assert env["MENTAT_SEED_SUMMARY"] == "prior ctx"
    assert captured["new_group"] is True


def test_spawn_worktree_subprocess_omits_flags_when_unset(tmp_path, monkeypatch):
    """No harness/model/seed → no flags and no MENTAT_SEED_SUMMARY env key."""
    spawn = load_module("spawn")
    routing = load_module("scheduler")
    plan = routing.Plan(slug="bare", kind="AFK", blocked_by=[], path=tmp_path / "p.md")

    monkeypatch.setattr(
        spawn,
        "_prepare_chunk_spawn",
        lambda p, **kw: (
            "sess-bare",
            ["python3", "impl"],
            {"MENTAT_AGENT": "sess-bare", "MENTAT_CHUNK_ID": "d" * 32},
            tmp_path / "wt",
        ),
    )

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return _FakePopen()

    monkeypatch.setattr(spawn.subprocess, "Popen", fake_popen)

    spawn._spawn_worktree_subprocess(plan)

    cmd = captured["cmd"]
    assert "--harness" not in cmd
    assert "--model" not in cmd
    assert "MENTAT_SEED_SUMMARY" not in captured["env"]
