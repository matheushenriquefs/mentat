"""S1: implement preflight + ro_mounts extracted under implement/."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / ".agents/skills/mentat-implement/scripts"
PKG = SCRIPTS / "implement"


def test_implement_subpackage_modules_exist() -> None:
    for name in ("preflight.py", "ro_mounts.py"):
        assert (PKG / name).is_file(), f"implement/{name} missing"


def test_implement_entry_imports_submodules() -> None:
    text = (SCRIPTS / "implement.py").read_text()
    assert "_load_sub" in text
    assert "implement/preflight" in text or "_preflight" in text
    assert "_ro_mounts" in text
