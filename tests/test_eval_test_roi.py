"""ROI test-reviewer promptfoo eval wiring (CS1) — assets present and self-consistent.

The eval itself needs an API key; this pins that the config, rubric, and fixtures
exist and reference each other, so the harness cannot rot silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "evals" / "promptfoo" / "test-roi"
CASES = ("padding", "lean-behavior", "assertion-free")


def _config() -> dict:
    return yaml.safe_load((EVAL_DIR / "promptfooconfig.yaml").read_text())


def test_config_exists_with_three_cases() -> None:
    tests = _config()["tests"]
    descriptions = " ".join(t["description"] for t in tests)
    assert "padding-flagged" in descriptions
    assert "lean-behavior-passed" in descriptions
    assert "assertion-free-rejected" in descriptions


def test_config_uses_the_reviewer_prompt_as_system() -> None:
    providers = _config()["providers"]
    systems = [p.get("config", {}).get("system", "") for p in providers]
    assert any("mentat-test-reviewer.md" in s for s in systems), "eval must drive the real reviewer prompt"


def test_rubric_exists() -> None:
    assert (ROOT / "evals" / "promptfoo" / "rubrics" / "mentat-test-reviewer-roi.md").exists()


@pytest.mark.parametrize("case", CASES)
def test_fixture_case_complete(case: str) -> None:
    base = EVAL_DIR.parent / "fixtures" / "test-roi" / case
    for name in ("plan.md", "tests.py", "diff.patch"):
        assert (base / name).exists(), f"missing {case}/{name}"


def test_padding_fixture_holds_padding_patterns() -> None:
    tests_py = (EVAL_DIR.parent / "fixtures" / "test-roi" / "padding" / "tests.py").read_text()
    assert "asserts nothing" in tests_py or "getter" in tests_py.lower()
