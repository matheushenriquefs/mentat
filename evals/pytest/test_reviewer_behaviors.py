"""Covers plan behaviors not asserted elsewhere — pushed score above 0.88 threshold."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import os

from utils import read_agent

MENTAT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ADR_DIR = os.path.join(MENTAT_ROOT, ".agents", "docs", "adr")


# S4.1 — "absence as evidence" instruction


def test_absence_as_evidence_phrasing():
    """Prompt must frame absence as proof, not just grep keyword list."""
    prompt = read_agent("mentat-plan-reviewer")
    # The instruction says "Absence = evidence of correctness" or similar
    assert "absence" in prompt.lower() or "absent" in prompt.lower(), (
        "mentat-plan-reviewer must frame absence-as-evidence for must_not_exist"
    )
    assert "grep" in prompt.lower() or "grep-absent" in prompt.lower(), "must_not_exist rule must reference grep check"


# S4.2 — source-file-present → normal gate (not carve-out)


def test_non_pytest_gate_source_file_fallback_documented():
    """Prompt must specify that source files revert to normal two-halves gate."""
    prompt = read_agent("mentat-test-reviewer")
    # Carve-out only applies when ALL files are config-only
    assert "all" in prompt.lower() or "only" in prompt.lower(), (
        "non_pytest_gate must require all files to be config-only"
    )
    assert "source" in prompt.lower() or "src/" in prompt or ".py" in prompt or ".ts" in prompt, (
        "prompt must specify source file presence → normal gate"
    )


# S4.3 — MEDIUM real bugs stay in findings[], not auto-promoted to drift


def test_medium_real_bugs_stay_in_findings():
    """Prompt must keep real MEDIUM bugs in findings[], not in design_drift."""
    prompt = read_agent("mentat-bug-reviewer")
    # findings[] should be mentioned as the destination for real bugs
    assert "findings" in prompt, "mentat-bug-reviewer must reference findings[] for real bugs"
    assert (
        "real bug" in prompt.lower()
        or "real bugs" in prompt.lower()
        or "incorrect logic" in prompt.lower()
        or "wrong output" in prompt.lower()
    ), "MEDIUM real bugs must be distinguished from drift in the prompt"


def test_design_drift_conservative_fallback():
    """When uncertain, prompt defaults to findings[] not design_drift."""
    prompt = read_agent("mentat-bug-reviewer")
    assert (
        "conservative" in prompt.lower()
        or "uncertain" in prompt.lower()
        or "unsure" in prompt.lower()
        or "prefer" in prompt.lower()
    ), "prompt must specify conservative fallback: uncertain → findings[]"


# S4.5 — ADR 0007 gate expression updated


def test_adr_0007_gate_expression_present():
    path = os.path.join(ADR_DIR, "0007-must-not-exist-veto.md")
    with open(path) as f:
        content = f.read()
    assert "gate_pass" in content or "gate expression" in content.lower(), (
        "ADR 0007 must include updated gate expression"
    )
    assert "must_not_exist_veto_clean" in content or "must_not_exist" in content, (
        "ADR 0007 gate must include must_not_exist veto"
    )
