"""Slice deepen-loader: lib/loader.py shared module loader."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType


def _loader_path() -> Path:
    return Path(__file__).resolve().parents[1] / "loader.py"


def _import_loader():
    import importlib.util as _ilu

    key = "lib.loader"
    spec = _ilu.spec_from_file_location(key, _loader_path())
    mod = _ilu.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return sys.modules[key]


def test_load_sibling_returns_module(tmp_path):
    loader = _import_loader()
    pkg = tmp_path / "pkg_x"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod_a.py").write_text("MARKER = 42\n")
    (pkg / "mod_b.py").write_text("")
    mod = loader.load_sibling(str(pkg / "mod_b.py"), "mod_a")
    assert isinstance(mod, ModuleType)
    assert mod.MARKER == 42


def test_load_sibling_caches_by_key(tmp_path):
    loader = _import_loader()
    pkg = tmp_path / "pkg_y"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod_c.py").write_text("MARKER = 99\n")
    (pkg / "mod_d.py").write_text("")
    m1 = loader.load_sibling(str(pkg / "mod_d.py"), "mod_c")
    m2 = loader.load_sibling(str(pkg / "mod_d.py"), "mod_c")
    assert m1 is m2


def test_load_skill_resolves_via_paths():
    loader = _import_loader()
    mod = loader.load_skill("mentat-log", "log")
    assert isinstance(mod, ModuleType)
    assert hasattr(mod, "main") or hasattr(mod, "build_parser")


def test_loader_stdlib_only():
    src = _loader_path().read_text()
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
