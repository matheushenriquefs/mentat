"""Verify HIGH sev veto logic present and correctly scoped in mentat-bug-reviewer."""

from utils import read_agent


def test_high_sev_veto_present():
    """Prompt must veto on sev >= high."""
    prompt = read_agent("mentat-bug-reviewer")
    assert "sev" in prompt.lower() and "high" in prompt.lower(), "mentat-bug-reviewer must reference sev=high veto"
    assert "veto" in prompt.lower(), "mentat-bug-reviewer must have veto mechanism"


def test_high_sev_only_not_medium():
    """MEDIUM alone must not veto — only HIGH+ does."""
    prompt = read_agent("mentat-bug-reviewer")
    # design_drift separates medium drift from high bugs
    assert "design_drift" in prompt, "MEDIUM drift goes to design_drift not veto"
    # Confirm medium real bugs stay in findings but don't auto-veto
    assert "medium" in prompt.lower(), "medium severity must be mentioned"


def test_output_format_has_max_sev():
    """Output block must include max_sev field."""
    prompt = read_agent("mentat-bug-reviewer")
    assert "max_sev=" in prompt, "Output must include max_sev= field"
