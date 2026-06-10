"""S4.4: eval harness scaffold — file/dir existence and tooling deps."""

import pytest

pytestmark = pytest.mark.skip(reason="shell-era: being updated for Python rewrite in bins-v2")

import json
import os

MENTAT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EVALS_ROOT = os.path.join(MENTAT_ROOT, ".agents", "evals")
AGENTS_DIR = os.path.join(MENTAT_ROOT, ".agents", "agents")
ADR_DIR = os.path.join(MENTAT_ROOT, ".agents", "docs", "adr")


def test_promptfoo_config_exists():
    path = os.path.join(EVALS_ROOT, "promptfoo", "promptfooconfig.yaml")
    assert os.path.isfile(path), f"Missing: {path}"


def test_promptfoo_rubrics_exist():
    rubrics_dir = os.path.join(EVALS_ROOT, "promptfoo", "rubrics")
    for name in ["mentat-plan-reviewer.md", "mentat-test-reviewer.md", "mentat-bug-reviewer.md"]:
        path = os.path.join(rubrics_dir, name)
        assert os.path.isfile(path), f"Missing rubric: {path}"


def test_fixture_dirs_exist():
    fixtures = [
        "handoff2-routes-not-dropped",
        "handoff4-taskfile-only",
        "handoff2-design-drift",
    ]
    fixtures_dir = os.path.join(EVALS_ROOT, "promptfoo", "fixtures")
    for fx in fixtures:
        for f in ["plan.md", "diff.patch"]:
            path = os.path.join(fixtures_dir, fx, f)
            assert os.path.isfile(path), f"Missing fixture: {path}"


def test_pytest_test_files_exist():
    test_files = [
        "test_veto_must_not_exist.py",
        "test_non_pytest_gate.py",
        "test_design_drift.py",
        "test_veto_max_sev_high.py",
        "test_blacklist.py",
    ]
    pytest_dir = os.path.join(EVALS_ROOT, "pytest")
    for f in test_files:
        path = os.path.join(pytest_dir, f)
        assert os.path.isfile(path), f"Missing test: {path}"


def test_package_json_declares_promptfoo():
    path = os.path.join(MENTAT_ROOT, "package.json")
    assert os.path.isfile(path), "package.json missing"
    with open(path) as f:
        pkg = json.load(f)
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert "promptfoo" in deps, "package.json must declare promptfoo dependency"


def test_pyproject_declares_pytest():
    path = os.path.join(MENTAT_ROOT, "pyproject.toml")
    assert os.path.isfile(path), "pyproject.toml missing"
    with open(path) as f:
        content = f.read()
    assert "pytest" in content, "pyproject.toml must declare pytest dependency"


def test_adr_0007_exists():
    path = os.path.join(ADR_DIR, "0007-must-not-exist-veto.md")
    assert os.path.isfile(path), f"ADR 0007 missing: {path}"


def test_adr_0007_covers_three_drift_classes():
    path = os.path.join(ADR_DIR, "0007-must-not-exist-veto.md")
    with open(path) as f:
        content = f.read()
    assert "must_not_exist" in content, "ADR 0007 must document must_not_exist veto"
    assert "non_pytest_gate" in content or "non_pytest" in content, "ADR 0007 must document non_pytest_gate"
    assert "design_drift" in content, "ADR 0007 must document design_drift surface"
