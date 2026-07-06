"""Slice deepen-events: lib/events.py bind() emitter."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from unittest.mock import patch


def _import_events():
    import importlib.util as _ilu

    key = "lib.events"
    spec = _ilu.spec_from_file_location(
        key,
        Path(__file__).resolve().parents[1] / ".agents/lib/events.py",
    )
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]


def test_bind_returns_callable():
    events = _import_events()
    emit = events.bind("mentat-skill")
    assert callable(emit)


def test_emit_invokes_log_script_with_skill_name():
    import subprocess

    events = _import_events()
    from lib.support import paths

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        emit = events.bind("mentat-foo")
        emit("foo.started", {"x": 1})

    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv == ["python3", str(paths.LOG_SCRIPT), "emit", "mentat-foo", "foo.started", '{"x": 1}']


def test_emit_mints_session_into_child_env_when_unset(monkeypatch):
    """bind()'s guarantee: log.py always receives a MENTAT_AGENT — an opaque
    uuid minted into the child env when none is set, so its orphan fallback is
    unreachable. os.environ itself is never mutated."""
    import re
    import subprocess

    events = _import_events()
    monkeypatch.delenv("MENTAT_AGENT", raising=False)

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        events.bind("mentat-foo")("foo.started", {})

    child_env = mock_run.call_args.kwargs["env"]
    assert re.fullmatch(r"[0-9a-f]{32}", child_env["MENTAT_AGENT"])
    assert "MENTAT_AGENT" not in os.environ  # global env untouched


def test_emit_preserves_existing_session_in_child_env(monkeypatch):
    import subprocess

    events = _import_events()
    monkeypatch.setenv("MENTAT_AGENT", "abc123")

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        events.bind("mentat-foo")("foo.started", {})

    assert mock_run.call_args.kwargs["env"]["MENTAT_AGENT"] == "abc123"


def test_emit_failure_prints_to_stderr_nonblocking(capsys):
    import subprocess

    events = _import_events()

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 2
        mock_run.return_value.stderr = "boom\n"
        emit = events.bind("mentat-foo")
        result = emit("x", {})

    assert result is None
    captured = capsys.readouterr()
    assert "mentat-foo" in captured.err
    assert "emit 'x' failed rc=2" in captured.err


def test_terminal_emit_failure_raises():
    """chunk_landed / chunk_ejected rejected by log → caller gets RuntimeError, not silent None."""
    import subprocess

    events = _import_events()

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "validation failed\n"
        emit = events.bind("mentat-orchestrate")
        import pytest

        with pytest.raises(RuntimeError, match="terminal emit"):
            emit("chunk_landed", {"slug": "x", "sha": "a", "holding": "main"})


def test_non_terminal_emit_failure_is_best_effort(capsys):
    """Non-terminal events on failure print to stderr but do not raise."""
    import subprocess

    events = _import_events()

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "oops\n"
        emit = events.bind("mentat-orchestrate")
        result = emit("chunk_started", {"slug": "x", "plan": "p", "harness": "h", "worktree": "w"})

    assert result is None
    captured = capsys.readouterr()
    assert "failed" in captured.err


def test_spawned_payload_omits_recovery_fields_by_default():
    events = _import_events()
    payload = events.spawned_payload("slug", "plan.md", harness="claude-code", worktree="/wt")
    assert payload == {"slug": "slug", "plan": "plan.md", "harness": "claude-code", "worktree": "/wt"}
    assert "trigger" not in payload
    assert "attempt" not in payload


def test_spawned_payload_carries_recovery_trigger_and_attempt():
    """A recovery respawn stamps trigger + 1-based attempt so the outcome
    attributes to a recovery pass (events.py:131,133 true branches)."""
    events = _import_events()
    payload = events.spawned_payload(
        "slug", "plan.md", harness="claude-code", worktree="/wt", trigger="recovery", attempt=2
    )
    assert payload["trigger"] == "recovery"
    assert payload["attempt"] == 2


def test_emit_is_stdlib_only():
    src = (Path(__file__).resolve().parents[1] / ".agents/lib/events.py").read_text()
    tree = ast.parse(src)
    stdlib = sys.stdlib_module_names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib or node.module.startswith("lib"), f"non-stdlib from-import: {node.module}"
