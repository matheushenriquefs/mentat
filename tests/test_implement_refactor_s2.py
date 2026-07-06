"""S2: implement wedge extracted."""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts/implement"


def test_wedge_module_exists() -> None:
    assert (PKG / "wedge.py").is_file()


def test_wedge_exports_resolve_wedge() -> None:
    text = (PKG / "wedge.py").read_text()
    assert "def resolve_wedge" in text
    assert "def read_blocked_summary" in text
