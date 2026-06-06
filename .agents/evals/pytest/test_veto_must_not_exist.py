"""S4.1: must_not_exist veto fires when plan removes entities still present in diff."""
from conftest import read_agent, read_fixture


def test_must_not_exist_veto_in_prompt():
    """Reviewer prompt must contain must_not_exist logic."""
    prompt = read_agent("crew-review-plan")
    assert "must_not_exist" in prompt, "crew-review-plan.md missing must_not_exist veto"
    assert "drop" in prompt.lower() or "remove" in prompt.lower(), (
        "must_not_exist rule must mention drop/remove keywords"
    )
    assert "VETO" in prompt, "must_not_exist must emit VETO"


def test_must_not_exist_fixture_has_retained_entities():
    """Fixture diff retains entities that plan said to drop."""
    diff = read_fixture("handoff2-routes-not-dropped", "diff.patch")
    plan = read_fixture("handoff2-routes-not-dropped", "plan.md")

    # Plan says drop these; diff must still contain them (that's the failure case)
    assert "/api/v1/users" in diff or "legacy_router" in diff, (
        "Fixture diff must retain at least one entity the plan said to drop"
    )
    assert "must not" in plan.lower() or "remove" in plan.lower() or "drop" in plan.lower(), (
        "Fixture plan must contain removal language"
    )


def test_must_not_exist_rule_covers_all_keywords():
    """Prompt must trigger on all required removal keywords."""
    prompt = read_agent("crew-review-plan")
    for keyword in ["drop", "remove", "replace", "no longer", "must not", "should not"]:
        assert keyword in prompt, f"must_not_exist rule missing keyword: {keyword}"
