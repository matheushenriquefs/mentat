"""S4.2: non_pytest_gate carve-out for config-only diffs."""
from conftest import read_agent, read_fixture


def test_non_pytest_gate_in_prompt():
    """Reviewer prompt must contain non_pytest_gate logic."""
    prompt = read_agent("crew-review-tests")
    assert "non_pytest_gate" in prompt, "crew-review-tests.md missing non_pytest_gate carve-out"
    assert "gate_type" in prompt, "non_pytest_gate must emit gate_type field"


def test_non_pytest_gate_covers_config_patterns():
    """Prompt must list key config-only file patterns."""
    prompt = read_agent("crew-review-tests")
    for pattern in ["Taskfile", "Dockerfile", ".github/workflows", "pyproject.toml", "package.json"]:
        assert pattern in prompt, f"non_pytest_gate missing config pattern: {pattern}"


def test_non_pytest_gate_fixture_is_config_only():
    """Fixture diff must touch only config files."""
    diff = read_fixture("handoff4-taskfile-only", "diff.patch")
    assert "Taskfile.yml" in diff, "Fixture must change Taskfile.yml"
    # Must not touch source files
    assert ".py" not in diff and ".ts" not in diff, (
        "Fixture must be config-only (no .py/.ts changes)"
    )


def test_non_pytest_gate_no_score_on_config():
    """Prompt must specify score=N/A for config-only diffs."""
    prompt = read_agent("crew-review-tests")
    assert "N/A" in prompt or "score=N/A" in prompt, (
        "non_pytest_gate must specify score=N/A output"
    )
