"""ReviewVerdict domain model — validated parse of reviewer JSON (CS1)."""

from __future__ import annotations

import pytest


def _verdict_mod():
    from lib.gates import verdict

    return verdict


def test_from_raw_full_valid_shape():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw(
        {
            "reviewer": "mentat-test-reviewer",
            "asserts_plan": 0.91,
            "veto": "clean",
            "findings": [{"file": "a.py", "line": 12, "reason": "getter", "severity": "low"}],
            "surviving_mutants": ["a.py:20", "b.py:5"],
        }
    )
    assert out.reviewer == "mentat-test-reviewer"
    assert out.asserts_plan == 0.91
    assert out.veto == "clean"
    assert out.findings == (v.Finding(file="a.py", line=12, reason="getter", severity="low"),)
    assert out.surviving_mutants == ("a.py:20", "b.py:5")


def test_frozen_dataclass_is_immutable():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw({"asserts_plan": 0.9})
    with pytest.raises(AttributeError):
        out.asserts_plan = 0.1  # type: ignore[misc]


# ── veto_clean fail-closed ───────────────────────────────────────────────────


def test_veto_clean_absent_is_clean():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({}).veto_clean is True


def test_veto_clean_exact_clean_is_clean():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({"veto": "clean"}).veto_clean is True


def test_veto_clean_empty_string_not_clean():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({"veto": ""}).veto_clean is False


def test_veto_clean_zero_not_clean():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw({"veto": 0})
    assert out.veto == "0"
    assert out.veto_clean is False


def test_veto_clean_false_not_clean():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({"veto": False}).veto_clean is False


def test_veto_reason_string_kept_and_not_clean():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw({"veto": "tripped: deleted assertion"})
    assert out.veto == "tripped: deleted assertion"
    assert out.veto_clean is False


# ── asserts_plan coercion ────────────────────────────────────────────────────


def test_asserts_plan_defaults_to_zero():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({}).asserts_plan == 0.0


def test_asserts_plan_coerces_numeric_string():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({"asserts_plan": "0.9"}).asserts_plan == 0.9


def test_asserts_plan_invalid_raises():
    v = _verdict_mod()
    with pytest.raises(v.VerdictError):
        v.ReviewVerdict.from_raw({"asserts_plan": "not-a-number"})


# ── findings validation ──────────────────────────────────────────────────────


def test_findings_absent_is_empty_tuple():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({}).findings == ()


def test_findings_default_severity_is_medium():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw({"findings": [{"file": "a.py", "line": 1, "reason": "x"}]})
    assert out.findings[0].severity == "medium"


def test_findings_non_list_raises():
    v = _verdict_mod()
    with pytest.raises(v.VerdictError):
        v.ReviewVerdict.from_raw({"findings": {"file": "a.py"}})


def test_finding_non_object_raises():
    v = _verdict_mod()
    with pytest.raises(v.VerdictError):
        v.ReviewVerdict.from_raw({"findings": ["a.py:1"]})


def test_finding_bad_severity_raises():
    v = _verdict_mod()
    with pytest.raises(v.VerdictError):
        v.ReviewVerdict.from_raw({"findings": [{"file": "a.py", "line": 1, "reason": "x", "severity": "critical"}]})


# ── surviving_mutants (advisory) ─────────────────────────────────────────────


def test_surviving_mutants_absent_is_empty_tuple():
    v = _verdict_mod()
    assert v.ReviewVerdict.from_raw({}).surviving_mutants == ()


def test_surviving_mutants_coerces_items_to_str():
    v = _verdict_mod()
    out = v.ReviewVerdict.from_raw({"surviving_mutants": ["a.py:1", 2]})
    assert out.surviving_mutants == ("a.py:1", "2")


def test_surviving_mutants_non_list_raises():
    v = _verdict_mod()
    with pytest.raises(v.VerdictError):
        v.ReviewVerdict.from_raw({"surviving_mutants": "a.py:1"})


# ── score_test consumes the model ────────────────────────────────────────────


def test_score_test_blocks_on_malformed_verdict():
    from lib.gates import score

    result = score.score_test({"asserts_plan": "garbage"})
    assert result.verdict == "block"
    assert "invalid" in result.reason


def test_score_test_advisory_mutants_do_not_block():
    from lib.gates import score

    result = score.score_test({"veto": "clean", "asserts_plan": 0.99, "surviving_mutants": ["a.py:1", "a.py:2"]})
    assert result.verdict == "pass"


def test_score_test_non_pytest_gate_passes_without_score():
    from lib.gates import score

    result = score.score_test({"reviewer": "mentat-test-reviewer", "gate_type": "non_pytest"})
    assert result.verdict == "pass"
