"""Shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest


def load_script(path: Path, key: str | None = None) -> ModuleType:
    """Import a free-standing .py script (not on sys.path) and return its module.

    Used by tests that load bin-layer scripts directly without packaging.
    The `key` defaults to the file stem; pass a unique key when loading the same
    file under different fixture conditions (e.g., different HOME).
    """
    if key is None:
        key = path.stem
    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def init_git_repo(path: Path, *, initial_branch: str = "main") -> None:
    """Initialize a git repo with an initial commit. Disables gpg signing.

    Used by worktree + preflight tests that need a real on-disk repo.
    """
    subprocess.run(
        ["git", "init", "-b", initial_branch, str(path)],
        check=True,
        capture_output=True,
    )
    for k, v in (
        ("user.email", "t@t"),
        ("user.name", "T"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(["git", "config", k, v], cwd=path, check=True, capture_output=True)
    (path / "README").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


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
