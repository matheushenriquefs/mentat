"""S4.3: design_drift surface — MEDIUM drift items separate from findings[]."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

from utils import read_agent, read_fixture


def test_design_drift_in_prompt():
    """Reviewer prompt must contain design_drift output field."""
    prompt = read_agent("mentat-bug-reviewer")
    assert "design_drift" in prompt, "mentat-bug-reviewer.md missing design_drift surface"


def test_design_drift_does_not_veto():
    """Prompt must explicitly state design_drift does not veto."""
    prompt = read_agent("mentat-bug-reviewer")
    # Must clarify drift ≠ veto
    assert (
        "not veto" in prompt.lower()
        or "does not veto" in prompt.lower()
        or "never veto" in prompt.lower()
        or "don't veto" in prompt.lower()
        or "doesn't veto" in prompt.lower()
        or "does NOT veto" in prompt
    ), "design_drift must be explicitly non-vetoing"


def test_design_drift_fixture_has_out_of_scope_items():
    """Fixture diff must contain items the plan marked out of scope."""
    diff = read_fixture("handoff2-design-drift", "diff.patch")
    plan = read_fixture("handoff2-design-drift", "plan.md")
    assert "rate limit" in diff.lower() or "limiter" in diff.lower() or "pagination" in diff.lower(), (
        "Fixture diff must contain out-of-scope additions"
    )
    assert "out of scope" in plan.lower() or "do not" in plan.lower(), (
        "Fixture plan must explicitly exclude the out-of-scope items"
    )


def test_design_drift_output_format():
    """design_drift must appear as a separate output field, not inside findings."""
    prompt = read_agent("mentat-bug-reviewer")
    # design_drift should be a named field in output block
    assert "design_drift:" in prompt or "design_drift[]" in prompt, "design_drift must be a named output field"
