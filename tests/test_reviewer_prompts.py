"""Reviewer prompt invariants — ADR-0003 scored review gate."""

from __future__ import annotations

from pathlib import Path

_AGENTS_DIR = Path(__file__).resolve().parents[1] / ".agents/agents"


def _read_agent(name: str) -> str:
    return (_AGENTS_DIR / f"{name}.md").read_text()


# ── ADR-0006 trajectory blacklist (mentat-bug-reviewer) ──────────────────


def test_blacklist_section_present():
    prompt = _read_agent("mentat-bug-reviewer").lower()
    assert "blacklist" in prompt, "mentat-bug-reviewer must have trajectory blacklist"


def test_blacklist_covers_runner_redirection():
    prompt = _read_agent("mentat-bug-reviewer").lower()
    assert "redirect" in prompt or "writable" in prompt, "blacklist must cover runner redirection (ADR-0006)"


def test_blacklist_covers_test_deletion():
    prompt = _read_agent("mentat-bug-reviewer").lower()
    assert "delete" in prompt or "empty" in prompt, "blacklist must cover test file deletion/emptying"


# ── HIGH-sev veto scope (mentat-bug-reviewer) ────────────────────────────


def test_high_sev_veto_present():
    prompt = _read_agent("mentat-bug-reviewer")
    low = prompt.lower()
    assert "sev" in low and "high" in low, "mentat-bug-reviewer must reference sev=high veto"
    assert "veto" in low, "mentat-bug-reviewer must have veto mechanism"


def test_high_sev_only_not_medium():
    prompt = _read_agent("mentat-bug-reviewer")
    assert "design_drift" in prompt, "MEDIUM drift goes to design_drift not veto"
    assert "medium" in prompt.lower(), "medium severity must be mentioned"


def test_output_format_has_max_sev():
    prompt = _read_agent("mentat-bug-reviewer")
    assert "max_sev=" in prompt, "output must include max_sev= field"


# ── VG3 veto-status alignment (rules + context reviewers) ────────────────────


def test_rules_reviewer_is_not_advisory():
    """rules-reviewer must not self-describe as advisory — it is a veto gate (ADR-0003 v5)."""
    prompt = _read_agent("mentat-rules-reviewer").lower()
    assert "advisory" not in prompt, (
        "mentat-rules-reviewer self-describes as advisory but score.py routes it as a "
        "veto gate (ADR-0003 v5). Remove advisory wording."
    )


def test_rules_reviewer_is_veto():
    prompt = _read_agent("mentat-rules-reviewer").lower()
    assert "veto" in prompt, "mentat-rules-reviewer must state it is a veto gate (ADR-0003 v5)"


def test_context_reviewer_is_veto():
    prompt = _read_agent("mentat-context-reviewer").lower()
    assert "veto" in prompt, "mentat-context-reviewer must state it is a veto gate (ADR-0003 v5)"
