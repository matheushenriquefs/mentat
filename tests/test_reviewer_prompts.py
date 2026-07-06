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


# ── CS1 test-reviewer ROI lens (mentat-test-reviewer) ────────────────────────


def test_test_reviewer_has_primary_question():
    """The reviewer must lead with the fail-on-bug ∩ survive-refactor heuristic."""
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "fail if a real bug" in prompt, "test-reviewer must ask the fail-on-bug half of the primary question"
    assert "refactor" in prompt, "test-reviewer must ask the survive-refactor half of the primary question"


def test_test_reviewer_has_priority_ladder():
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "priority ladder" in prompt, "test-reviewer must carry the value priority ladder"
    assert "state over interaction" in prompt, "ladder must prefer state over interaction (Google)"


def test_test_reviewer_has_never_assert_list():
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "never assert" in prompt, "test-reviewer must penalize the never-assert padding list"
    assert "getter" in prompt, "never-assert list must call out getters"


def test_test_reviewer_has_mock_smell_penalty():
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "mock" in prompt, "test-reviewer must carry the mock-smell penalty"
    assert "don't mock types you don't own" in prompt, "mock-smell must cite the don't-mock-what-you-don't-own rule"


def test_test_reviewer_mock_nuance_not_blanket_ban():
    """Classicist-vs-mockist is a real split: interaction asserts are legit when the contract."""
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "blanket-ban" in prompt or "blanket ban" in prompt, "mock nuance must reject a blanket ban"
    assert "idempoten" in prompt, "must give the idempotency example where interaction IS the contract"


def test_test_reviewer_consumes_mutation_advisory():
    prompt = _read_agent("mentat-test-reviewer").lower()
    assert "surviving_mutants" in prompt, "test-reviewer must consume the advisory surviving-mutants list"
    assert "advisory" in prompt, "mutation input must be framed as advisory, never a gate"


def test_test_reviewer_emits_review_verdict_json():
    prompt = _read_agent("mentat-test-reviewer")
    assert "ReviewVerdict" in prompt, "test-reviewer output must be a typed ReviewVerdict"
    low = prompt.lower()
    assert "json" in low, "output must be JSON parsed without regex"
    assert "asserts_plan" in prompt, "verdict must carry asserts_plan"


def test_test_reviewer_keeps_threshold_and_veto():
    prompt = _read_agent("mentat-test-reviewer")
    assert "0.88" in prompt, "asserts-plan threshold 0.88 must be unchanged"
    assert "veto" in prompt.lower(), "deterministic veto must remain"
