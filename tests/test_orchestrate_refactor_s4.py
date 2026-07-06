"""S4: orchestrate tests mirrored under tests/orchestrate/ with real_audit_store."""

from __future__ import annotations

from pathlib import Path

MIRROR = Path(__file__).resolve().parents[1] / "tests" / "orchestrate"


def test_orchestrate_mirror_package_exists() -> None:
    assert MIRROR.is_dir()
    modules = sorted(MIRROR.glob("test_*.py"))
    assert len(modules) >= 12


def test_emit_mirror_uses_real_audit_store() -> None:
    text = (MIRROR / "test_orchestrate_emit.py").read_text()
    assert "real_audit_store" in text
