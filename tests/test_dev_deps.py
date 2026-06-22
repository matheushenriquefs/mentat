"""Verify coverage is declared as a dev dependency."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dev_deps() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return data["dependency-groups"]["dev"]


def test_coverage_declared_as_dev_dep() -> None:
    deps = _dev_deps()
    assert any("coverage" in d for d in deps), f"coverage not in dev deps: {deps}"
