"""ADR 0006 trajectory blacklist veto — reward-hacking moves caught."""
from utils import read_agent


def test_blacklist_section_present():
    """Trajectory blacklist section must exist in crew-review-bugs."""
    prompt = read_agent("crew-review-bugs")
    assert "blacklist" in prompt.lower(), "crew-review-bugs must have trajectory blacklist"


def test_blacklist_covers_runner_redirection():
    """ADR 0006: runner redirection must be a blacklisted move."""
    prompt = read_agent("crew-review-bugs")
    assert "redirect" in prompt.lower() or "writable" in prompt.lower(), (
        "Blacklist must cover runner redirection (ADR 0006)"
    )


def test_blacklist_covers_test_deletion():
    """Deleting test files must be blacklisted."""
    prompt = read_agent("crew-review-bugs")
    assert "delete" in prompt.lower() or "empty" in prompt.lower(), (
        "Blacklist must cover test file deletion/emptying"
    )


def test_blacklist_output_format():
    """Output must include blacklist= field."""
    prompt = read_agent("crew-review-bugs")
    assert "blacklist=" in prompt, "Output must include blacklist= field"
