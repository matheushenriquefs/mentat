"""S3: guardrails.py extracted from supervise.py."""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents/skills/mentat-orchestrate/scripts"


def test_guardrails_module_exists() -> None:
    assert (SCRIPTS / "guardrails.py").is_file()


def test_supervise_imports_guardrails() -> None:
    text = (SCRIPTS / "supervise.py").read_text()
    assert "_guardrails" in text
    assert "CircuitBreaker" in text


def test_supervise_under_350_loc() -> None:
    lines = [ln for ln in SCRIPTS.joinpath("supervise.py").read_text().splitlines() if ln.strip()]
    assert len(lines) < 350, f"supervise.py still {len(lines)} non-blank lines"
