"""S4: track tests mirrored under tests/track/ with real_audit_store."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACK_TESTS = REPO_ROOT / "tests" / "track"


def test_track_mirror_package_exists() -> None:
    assert TRACK_TESTS.is_dir(), "tests/track/ mirror missing"
    modules = sorted(TRACK_TESTS.glob("test_*.py"))
    assert modules, "tests/track/ has no test modules"


def test_track_mirror_uses_real_audit_store_fixture() -> None:
    text = (TRACK_TESTS / "test_list.py").read_text()
    assert "real_audit_store" in text
