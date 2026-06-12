"""Slice deepen-jsonc: lib/jsonc.py load_jsonc + read_config."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


def _jsonc_path() -> Path:
    return Path(__file__).resolve().parents[1] / "jsonc.py"


def _import_jsonc():
    import importlib.util as _ilu

    key = "lib.jsonc"
    spec = _ilu.spec_from_file_location(key, _jsonc_path())
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]


def test_load_jsonc_strips_line_comments(tmp_path):
    m = _import_jsonc()
    f = tmp_path / "config.jsonc"
    f.write_text('{"a": 1, // comment\n"b": 2}')
    assert m.load_jsonc(f) == {"a": 1, "b": 2}


def test_load_jsonc_returns_empty_on_invalid(tmp_path):
    m = _import_jsonc()
    f = tmp_path / "bad.jsonc"
    f.write_text("{not valid json")
    assert m.load_jsonc(f) == {}


def test_read_config_global_only(tmp_path):
    m = _import_jsonc()
    (tmp_path / ".mentat").mkdir()
    (tmp_path / ".mentat" / "config.jsonc").write_text('{"harness": "test-harness"}')

    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(subprocess, "run") as mock_run,
    ):
        mock_run.return_value.returncode = 1  # git rev-parse fails → no repo cfg
        result = m.read_config()

    assert result.get("harness") == "test-harness"


def test_read_config_repo_overrides_global(tmp_path):
    m = _import_jsonc()
    global_dir = tmp_path / "global_home"
    global_dir.mkdir()
    (global_dir / ".mentat").mkdir()
    (global_dir / ".mentat" / "config.jsonc").write_text('{"harness": "global", "key": "from-global"}')

    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    (repo_dir / ".mentat").mkdir()
    (repo_dir / ".mentat" / "config.jsonc").write_text('{"harness": "repo"}')

    with (
        patch("pathlib.Path.home", return_value=global_dir),
        patch.object(subprocess, "run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = str(repo_dir) + "\n"
        result = m.read_config()

    assert result["harness"] == "repo"
    assert result["key"] == "from-global"


def test_jsonc_stdlib_only():
    src = _jsonc_path().read_text()
    tree = ast.parse(src)
    stdlib = sys.stdlib_module_names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib, f"non-stdlib from-import: {node.module}"
