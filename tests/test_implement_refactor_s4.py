"""S4: implement tests mirrored under tests/implement/ with real_audit_store."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIRROR = REPO_ROOT / "tests" / "implement"


def test_implement_mirror_package_exists() -> None:
    assert MIRROR.is_dir()
    modules = sorted(MIRROR.glob("test_*.py"))
    assert len(modules) >= 7


def test_emit_mirror_uses_real_audit_store() -> None:
    text = (MIRROR / "test_emit.py").read_text()
    assert "real_audit_store" in text
