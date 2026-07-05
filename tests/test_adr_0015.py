"""S4: ADR-0015 auto-recovery is recorded, indexed, and referenced by the engine."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_ADR = _ROOT / "docs/adr/0015-auto-recovery.md"
_SCRIPTS = _ROOT / ".agents/skills/mentat-orchestrate/scripts"


def test_adr_0015_exists_with_accepted_status():
    assert _ADR.exists(), "ADR-0015 file must exist"
    text = _ADR.read_text()
    assert "# ADR 0015:" in text
    assert "Status: Superseded" in text or "Status: Accepted" in text


def test_adr_0015_listed_in_index():
    index = (_ROOT / "docs/adr/README.md").read_text()
    assert "0015-auto-recovery.md" in index, "ADR-0015 must be in the ADR index"


def test_adr_0015_records_the_contract():
    text = _ADR.read_text()
    # The settled contract points the ADR must record.
    for token in ("transient", "terminal", "retry", "reslice", "abandon", "idempotent", "storm", "budget", "escalate"):
        assert token in text.lower(), f"ADR-0015 must document {token!r}"


def test_engine_code_references_adr_0015():
    recover = (_SCRIPTS / "recover.py").read_text()
    orchestrate = (_SCRIPTS / "orchestrate.py").read_text()
    assert "ADR-0015" in recover, "recover.py must reference ADR-0015"
    assert "ADR-0015" in orchestrate, "orchestrate.py must reference ADR-0015"
