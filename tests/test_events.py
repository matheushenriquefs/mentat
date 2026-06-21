"""Slice deepen-events: lib/events.py bind() emitter."""

from __future__ import annotations

import ast
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
    from lib import paths

    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        emit = events.bind("mentat-foo")
        emit("foo.started", {"x": 1})

    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv == ["python3", str(paths.LOG_SCRIPT), "emit", "mentat-foo", "foo.started", '{"x": 1}']


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
