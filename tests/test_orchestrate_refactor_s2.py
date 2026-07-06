"""S2: cleanup.py extracted from batch.py."""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def test_cleanup_module_exists() -> None:
    assert (SCRIPTS / "cleanup.py").is_file()


def test_batch_delegates_prune_to_cleanup() -> None:
    text = (SCRIPTS / "batch.py").read_text()
    assert "_cleanup" in text
    assert "prune_stale_containers" in text
