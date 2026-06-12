"""Slice deepen-paths: lib/paths.py frozen path constants."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest


def _import_paths():
    import importlib.util as _ilu

    key = "lib.paths"
    spec = _ilu.spec_from_file_location(
        key,
        Path(__file__).resolve().parents[1] / "paths.py",
    )
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod  # register first so __name__ lookup inside paths.py works
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]  # may be replaced by frozen dataclass


def test_paths_constants_resolve_to_existing_dirs():
    paths = _import_paths()
    assert isinstance(paths.AGENTS_DIR, Path)
    assert paths.AGENTS_DIR.name == ".agents"
    assert paths.AGENTS_DIR.exists()

    assert isinstance(paths.LIB_DIR, Path)
    assert paths.LIB_DIR.name == "lib"
    assert paths.LIB_DIR.exists()

    assert isinstance(paths.SKILLS_DIR, Path)
    assert paths.SKILLS_DIR.name == "skills"
    assert paths.SKILLS_DIR.exists()

    assert isinstance(paths.LOG_SCRIPT, Path)
    assert paths.LOG_SCRIPT.parts[-1] == "log.py"
    assert "mentat-log" in str(paths.LOG_SCRIPT)
    assert paths.LOG_SCRIPT.is_file()

    assert isinstance(paths.GATES_CODE_DIR, Path)
    assert paths.GATES_CODE_DIR.parts[-1] == "code"
    assert "gates" in str(paths.GATES_CODE_DIR)
    assert paths.GATES_CODE_DIR.is_dir()


def test_paths_module_is_stdlib_only():
    src = (Path(__file__).resolve().parents[1] / "paths.py").read_text()
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


def test_paths_frozen():
    paths = _import_paths()
    assert isinstance(paths.AGENTS_DIR, Path)
    with pytest.raises((AttributeError, TypeError)):
        paths.AGENTS_DIR = Path("/")
