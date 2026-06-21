"""Tests for tasks/coverage.py runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("coverage", reason="coverage not installed in this Python env")

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "tasks" / "coverage.py"


def _make_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal src package + test under tmp_path."""
    src = tmp_path / "myfix"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "math_.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n")

    tests = tmp_path / "fixtests"
    tests.mkdir()
    (tests / "test_math.py").write_text(
        "from myfix.math_ import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n"
    )
    return src, tests


def test_coverage_runner_exit_zero_and_report(tmp_path: Path) -> None:
    src, tests = _make_fixture(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(RUNNER), f"--source={src.name}", str(tests)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOTAL" in result.stdout


def test_coverage_runner_produces_json(tmp_path: Path) -> None:
    src, tests = _make_fixture(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    subprocess.run(
        [sys.executable, str(RUNNER), f"--source={src.name}", str(tests)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    json_file = tmp_path / "coverage.json"
    assert json_file.exists(), "coverage.json not created"
    data = json.loads(json_file.read_text())
    assert "totals" in data
    assert "percent_covered" in data["totals"]
