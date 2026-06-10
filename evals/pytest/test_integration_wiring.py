"""Behaviors 3/10/11: promptfoo assertions, mentat-container-run wiring, mentat-orchestrate hook."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import os

MENTAT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TO_ORCHESTRATE = os.path.expanduser("~/.agents/bin/mentat-orchestrate")
PROMPTFOO_CONFIG = os.path.join(MENTAT_ROOT, "evals", "promptfoo", "promptfooconfig.yaml")


# Behavior 3: promptfooconfig.yaml asserts veto fires on routes-not-dropped fixture


def test_promptfoo_config_asserts_veto_must_not_exist():
    """promptfooconfig.yaml must assert VETO must_not_exist for routes-not-dropped test."""
    with open(PROMPTFOO_CONFIG) as f:
        content = f.read()
    assert "VETO must_not_exist" in content, (
        "promptfooconfig.yaml must assert 'VETO must_not_exist' for handoff2-routes-not-dropped"
    )


def test_promptfoo_config_asserts_non_pytest_gate():
    """promptfooconfig.yaml must assert gate_type=non_pytest for taskfile-only fixture."""
    with open(PROMPTFOO_CONFIG) as f:
        content = f.read()
    assert "gate_type=non_pytest" in content, (
        "promptfooconfig.yaml must assert gate_type=non_pytest for handoff4-taskfile-only"
    )


def test_promptfoo_config_asserts_design_drift():
    """promptfooconfig.yaml must assert design_drift in output for design-drift fixture."""
    with open(PROMPTFOO_CONFIG) as f:
        content = f.read()
    assert "design_drift" in content, "promptfooconfig.yaml must assert design_drift for handoff2-design-drift"


# Behavior 10: conftest.py exposes devcontainer_run for container-routed invocation


def test_conftest_defines_devcontainer_run():
    """conftest.py must define devcontainer_run so evals can be container-routed."""
    conftest_path = os.path.join(os.path.dirname(__file__), "conftest.py")
    with open(conftest_path) as f:
        content = f.read()
    assert "devcontainer_run" in content, (
        "conftest.py must define devcontainer_run for container-routed eval invocation"
    )
    assert "mentat-container-run" in content, "devcontainer_run must call ~/.agents/bin/mentat-container-run"


# Behavior 11: mentat-orchestrate runs end-of-queue evals


def test_to_orchestrate_has_end_of_queue_eval():
    """mentat-orchestrate must run evals/pytest at end of queue when all chunks land."""
    assert os.path.isfile(TO_ORCHESTRATE), f"mentat-orchestrate not found: {TO_ORCHESTRATE}"
    with open(TO_ORCHESTRATE) as f:
        content = f.read()
    assert "evals" in content, "mentat-orchestrate must reference evals for end-of-queue eval run"
    assert "pytest" in content, "mentat-orchestrate must invoke pytest as part of end-of-queue eval harness"


def test_to_orchestrate_evals_conditional_on_all_pass():
    """mentat-orchestrate must only run evals when FAILED -eq 0 (all chunks passed)."""
    with open(TO_ORCHESTRATE) as f:
        content = f.read()
    # The eval invocation must appear in the FAILED==0 branch, not the failure branch
    idx_evals = content.find("evals")
    idx_failed_0 = content.find('FAILED" -eq 0')
    idx_failed_else = content.rfind("FAILED")
    assert idx_failed_0 < idx_evals, "eval invocation must appear after the FAILED==0 check"
