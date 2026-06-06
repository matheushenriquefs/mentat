import subprocess
import os
import pytest

AGENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "agents")
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "promptfoo", "fixtures")


def devcontainer_run(cmd: str) -> subprocess.CompletedProcess:
    """Run cmd inside devcontainer via ~/.agents/bin/devcontainer-run."""
    result = subprocess.run(
        [os.path.expanduser("~/.agents/bin/devcontainer-run"), cmd],
        capture_output=True,
        text=True,
    )
    return result


def read_fixture(name: str, filename: str) -> str:
    path = os.path.join(FIXTURES_DIR, name, filename)
    with open(path) as f:
        return f.read()


def read_agent(name: str) -> str:
    path = os.path.join(AGENTS_DIR, f"{name}.md")
    with open(path) as f:
        return f.read()


@pytest.fixture
def reviewer_crew_review_plan():
    return read_agent("crew-review-plan")


@pytest.fixture
def reviewer_crew_review_tests():
    return read_agent("crew-review-tests")


@pytest.fixture
def reviewer_crew_review_bugs():
    return read_agent("crew-review-bugs")
