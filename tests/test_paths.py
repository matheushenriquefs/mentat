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
        Path(__file__).resolve().parents[1] / ".agents/lib/paths.py",
    )
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod  # register first so __name__ lookup inside paths.py works
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]  # may be replaced by frozen dataclass


def test_paths_mentat_dir_fields():
    """New home-dir anchors for mentat-private surface (ADR-0008 revised)."""
    paths = _import_paths()

    assert isinstance(paths.MENTAT_DIR, Path)
    assert paths.MENTAT_DIR.name == ".mentat"
    assert paths.MENTAT_DIR.parent == Path.home()

    assert isinstance(paths.MENTAT_LIB_DIR, Path)
    assert paths.MENTAT_LIB_DIR == paths.MENTAT_DIR / "lib"

    assert isinstance(paths.MENTAT_BIN_DIR, Path)
    assert paths.MENTAT_BIN_DIR == paths.MENTAT_DIR / "bin"

    assert isinstance(paths.MENTAT_DOCS_DIR, Path)
    assert paths.MENTAT_DOCS_DIR == paths.MENTAT_DIR / "docs"

    assert isinstance(paths.MENTAT_WORKTREES_DIR, Path)
    assert paths.MENTAT_WORKTREES_DIR == paths.MENTAT_DIR / "worktrees"


def test_paths_agents_dir_home_based():
    """AGENTS_DIR is now home-dir based, not file-relative (ADR-0008 revised)."""
    paths = _import_paths()

    assert isinstance(paths.AGENTS_DIR, Path)
    assert paths.AGENTS_DIR.name == ".agents"
    assert paths.AGENTS_DIR.parent == Path.home()

    assert isinstance(paths.SKILLS_DIR, Path)
    assert paths.SKILLS_DIR == paths.AGENTS_DIR / "skills"

    assert isinstance(paths.PLANS_DIR, Path)
    assert paths.PLANS_DIR == paths.AGENTS_DIR / "plans"


def test_paths_derived_fields_structure():
    """Derived paths have correct structure regardless of host install state."""
    paths = _import_paths()

    assert isinstance(paths.LOG_SCRIPT, Path)
    assert paths.LOG_SCRIPT.parts[-1] == "log.py"
    assert "mentat-log" in str(paths.LOG_SCRIPT)

    assert isinstance(paths.CONTAINER_SCRIPT, Path)
    assert paths.CONTAINER_SCRIPT.parts[-1] == "container.py"
    assert "mentat-container" in str(paths.CONTAINER_SCRIPT)

    assert isinstance(paths.GATES_CODE_DIR, Path)
    assert paths.GATES_CODE_DIR.parts[-1] == "code"
    assert "gates" in str(paths.GATES_CODE_DIR)

    assert isinstance(paths.LOGS_DIR, Path)
    assert paths.LOGS_DIR.parts[-1] == "logs"


def test_paths_module_is_stdlib_only():
    src = (Path(__file__).resolve().parents[1] / ".agents/lib/paths.py").read_text()
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
