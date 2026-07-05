"""Shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import subprocess
import types
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

TEST_CHUNK_ID = "b" * 32


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


@pytest.fixture(autouse=True)
def _clear_chunk_registry() -> None:
    import lib.chunk as chunk_mod

    chunk_mod.clear_plan_chunks()
    yield
    chunk_mod.clear_plan_chunks()


@pytest.fixture(autouse=True)
def _isolate_state_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect sqlite stores to throwaway paths for every test."""
    monkeypatch.setenv("MENTAT_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    for key in (
        "MENTAT_AGENT",
        "MENTAT_SESSION",
        "MENTAT_AGENT_LOG",
        "MENTAT_SESSION_LOG",
        "MENTAT_AGENT_PID",
        "MENTAT_SESSION_PID",
        "MENTAT_SESSION_ROLE",
        "MENTAT_SESSION_SLUG",
        "MENTAT_SESSION_BRANCH",
        "MENTAT_SLUG",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def mentat_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Set MENTAT_LOG_PATH and MENTAT_CONFIG to tmp dirs. Return the tmp root."""
    log_path = tmp_path / "logs"
    log_path.mkdir()
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("MENTAT_LOG_PATH", str(log_path))
    monkeypatch.setenv("MENTAT_CONFIG", str(config_path))
    return tmp_path


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Generator[Path]:
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


def bind_chunk_worktrees(plans, root: Path, *, chunk_id: str | None = None) -> dict[str, Path]:
    """Bind ephemeral chunk ids for plan slugs and return slug→worktree paths."""
    import lib.chunk as chunk_mod

    out: dict[str, Path] = {}
    for plan in plans:
        slug = plan.slug if hasattr(plan, "slug") else str(plan)
        cid = chunk_id or chunk_mod.make_chunk_id()
        chunk_mod.bind_plan_chunk(slug, cid)
        wt = root / ".mentat" / "worktrees" / cid / slug
        wt.mkdir(parents=True, exist_ok=True)
        out[slug] = wt
    return out


def fake_plan(path: Path, slug: str | None = None) -> types.SimpleNamespace:
    slug = slug or path.stem
    return types.SimpleNamespace(slug=slug, path=path)


def bind_plan(slug: str, chunk_id: str = TEST_CHUNK_ID) -> str:
    import lib.chunk as chunk_mod

    chunk_mod.bind_plan_chunk(slug, chunk_id)
    return chunk_id


def chunk_label(slug: str, chunk_id: str = TEST_CHUNK_ID) -> str:
    return f"{chunk_id}/{slug}"


def mock_fan_out_worktree(monkeypatch, fan_out_mod, worktree: Path) -> None:
    monkeypatch.setattr(fan_out_mod, "_ensure_chunk_worktree", lambda slug, cid: worktree)


def patch_orchestrate_worktree(orch, root: Path):
    """Patch orchestrate._worktree_for_slug to chunk-keyed paths under root."""
    return patch.object(
        orch,
        "_worktree_for_slug",
        side_effect=lambda s: root / ".mentat" / "worktrees" / TEST_CHUNK_ID / s,
    )


def async_spawner(procs, worktree: Path):
    """Return spawn_async fake yielding (session_id, proc, worktree) per plan."""
    it = iter(procs)

    async def spawn_async(plan, *, harness=None, model=None, seed_summary=None):
        return (f"sess-{plan.slug}", next(it), worktree)

    return spawn_async


def chunk_worktree_target(parent: Path, slug: str, chunk_id: str = TEST_CHUNK_ID) -> Path:
    return (parent / chunk_id / slug).resolve()


def holding_branch(slug: str, chunk_id: str = TEST_CHUNK_ID) -> str:
    return f"mentat/{chunk_id}/{slug}"
