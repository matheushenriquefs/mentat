import os
import subprocess

import pytest

from utils import read_agent


def devcontainer_run(cmd: str) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [os.path.expanduser("~/.agents/bin/mentat-container-run"), cmd],
        capture_output=True,
        text=True,
    )
    return result


@pytest.fixture
def reviewer_crew_review_plan():
    return read_agent("mentat-plan-reviewer")


@pytest.fixture
def reviewer_crew_review_tests():
    return read_agent("mentat-test-reviewer")


@pytest.fixture
def reviewer_crew_review_bugs():
    return read_agent("mentat-bug-reviewer")
