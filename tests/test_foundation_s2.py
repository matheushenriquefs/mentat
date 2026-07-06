"""S2: chunk/config env accessors + lib dead-abstraction cleanup."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS = REPO_ROOT / ".agents"
LIB = AGENTS / "lib"

_CHUNK_RAW = re.compile(
    r"""os\.environ(?:\.get)?\s*\[\s*["']MENTAT_CHUNK_ID["']|os\.environ\.get\(\s*["']MENTAT_CHUNK_ID"""
)
_CONFIG_RAW = re.compile(r"""os\.environ(?:\.get)?\s*\[\s*["']MENTAT_CONFIG["']|os\.environ\.get\(\s*["']MENTAT_CONFIG|env\.get\(\s*["']MENTAT_CONFIG""")


def _runtime_py_files() -> list[Path]:
    roots = [LIB, AGENTS / "skills"]
    out: list[Path] = []
    for root in roots:
        out.extend(root.rglob("*.py"))
    return sorted(out)


def _is_accessor_file(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT)
    return rel in {
        Path(".agents/lib/chunk.py"),
        Path(".agents/lib/config.py"),
    }


def test_zero_raw_chunk_env_reads_outside_accessor() -> None:
    offenders: list[str] = []
    for path in _runtime_py_files():
        if _is_accessor_file(path):
            continue
        text = path.read_text()
        if "MENTAT_CHUNK_ID" not in text:
            continue
        if _CHUNK_RAW.search(text) or 'env.get("MENTAT_CHUNK_ID"' in text or "env.get('MENTAT_CHUNK_ID'" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"raw MENTAT_CHUNK_ID reads remain: {offenders}"


def test_zero_raw_config_env_reads_outside_accessor() -> None:
    offenders: list[str] = []
    for path in _runtime_py_files():
        if _is_accessor_file(path):
            continue
        text = path.read_text()
        if "MENTAT_CONFIG" not in text:
            continue
        if _CONFIG_RAW.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"raw MENTAT_CONFIG reads remain: {offenders}"


def test_no_empty_init_py_under_lib() -> None:
    empty: list[str] = []
    for path in LIB.rglob("__init__.py"):
        if path.read_text().strip() == "":
            empty.append(str(path.relative_to(REPO_ROOT)))
    assert empty == [], f"empty __init__.py files remain: {empty}"


def test_no_docstring_only_support_init() -> None:
    path = LIB / "support" / "__init__.py"
    assert not path.exists(), "docstring-only support/__init__.py should be deleted"


def test_gates_init_reexport_removed() -> None:
    assert not (LIB / "gates" / "__init__.py").exists()


def test_registry_has_no_dup_path_consts() -> None:
    src = (AGENTS / "skills" / "mentat-skill" / "scripts" / "registry.py").read_text()
    assert "_SKILL_ROOT" not in src
    assert "_SCRIPTS" not in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == ".agents":
            pytest.fail("registry.py must not hardcode .agents path segments")


def test_get_chunk_id_from_env_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    sys.path.insert(0, str(AGENTS))
    from lib.chunk import get_chunk_id_from_env

    monkeypatch.delenv("MENTAT_CHUNK_ID", raising=False)
    assert get_chunk_id_from_env() == ""
    monkeypatch.setenv("MENTAT_CHUNK_ID", "abc")
    assert get_chunk_id_from_env() == "abc"


def test_get_config_dir_default_and_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(AGENTS))
    from lib.config import get_config_dir

    monkeypatch.delenv("MENTAT_CONFIG", raising=False)
    default = get_config_dir()
    assert default.name == "config.toml"
    assert default.parent.name == ".mentat"
    cfg = tmp_path / "override.toml"
    monkeypatch.setenv("MENTAT_CONFIG", str(cfg))
    assert get_config_dir() == cfg
