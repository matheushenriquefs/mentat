"""Shared pytest fixtures."""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture
def mentat_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Set MENTAT_LOG_PATH and MENTAT_CONFIG to tmp dirs. Return the tmp root."""
    log_path = tmp_path / "logs"
    log_path.mkdir()
    config_path = tmp_path / "config.jsonc"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_path))
    monkeypatch.setenv("MENTAT_CONFIG", str(config_path))
    return tmp_path


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a minimal git repo with optional plan files. Yield the repo root."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        cwd=repo,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        check=True,
        capture_output=True,
        cwd=repo,
    )
    readme = repo / "README.md"
    readme.write_text("fixture repo\n")
    subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=repo)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        check=True,
        capture_output=True,
        cwd=repo,
    )
    yield repo
