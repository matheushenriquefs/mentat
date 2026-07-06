"""S3: implement diagnostics extracted; entry thinned."""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-implement/scripts"


def test_diagnostics_module_exists() -> None:
    assert (SCRIPTS / "implement/diagnostics.py").is_file()


def test_entry_under_450_loc() -> None:
    lines = [ln for ln in SCRIPTS.joinpath("implement.py").read_text().splitlines() if ln.strip()]
    assert len(lines) < 450, f"implement.py still {len(lines)} non-blank lines"
