"""S1: recover split into recovery/ subpackage."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG = REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/recovery"


def test_recovery_subpackage_modules_exist() -> None:
    for name in ("context.py", "decision.py", "guards.py"):
        assert (PKG / name).is_file(), f"recovery/{name} missing"


def test_recover_entry_loads_submodules() -> None:
    text = (REPO_ROOT / ".agents/skills/mentat-orchestrate/scripts/recover.py").read_text()
    assert "_load_sub" in text
    assert "_guards" in text
    assert "_context" in text
    assert "_decision" in text
