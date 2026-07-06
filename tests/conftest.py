"""Shared pytest fixtures."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import types
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
from lib.git import scrub_ambient_git_env

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_CHUNK_ID = "b" * 32


def git_isolation_env(ceiling: Path) -> dict[str, str]:
    """Git env that blocks upward discovery past ``ceiling``."""
    env = scrub_ambient_git_env()
    env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return env


def strip_git_hook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop inherited git/lefthook vars (GIT_INDEX_FILE, GIT_DIR, LEFTHOOK, …)."""
    for key in list(os.environ):
        if key == "GIT_CEILING_DIRECTORIES":
            continue
        if key.startswith("GIT_") or key.startswith("LEFTHOOK"):
            monkeypatch.delenv(key, raising=False)


def subprocess_env(**overrides: str) -> dict[str, str]:
    """Subprocess env without inherited GIT_/LEFTHOOK hook context."""
    env = scrub_ambient_git_env()
    env.update(overrides)
    return env


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


def init_git_repo(path: Path, *, initial_branch: str = "main", ceiling: Path | None = None) -> None:
    """Initialize a git repo with an initial commit. Disables gpg signing.

    Used by worktree + preflight tests that need a real on-disk repo.
    """
    ceiling = ceiling or path.parent
    env = git_isolation_env(ceiling)
    subprocess.run(
        ["git", "init", "-b", initial_branch, str(path)],
        check=True,
        capture_output=True,
        env=env,
    )
    for k, v in (
        ("user.email", "t@t"),
        ("user.name", "T"),
        ("commit.gpgsign", "false"),
    ):
        subprocess.run(
            ["git", "config", k, v],
            cwd=path,
            check=True,
            capture_output=True,
            env=env,
        )
    (path / "README").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True, env=env)


@pytest.fixture(autouse=True)
def _clear_chunk_registry() -> None:
    import lib.chunk as chunk_mod

    chunk_mod.clear_plan_chunks()
    yield
    chunk_mod.clear_plan_chunks()


@pytest.fixture(autouse=True)
def _default_git_commit_identity(
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    """Orchestrate paths call require_commit_identity; tmp sandboxes have no git config."""
    nodeid = request.node.nodeid
    if "test_lib_git.py" in nodeid and ("require_commit_identity" in nodeid or "host_commit_identity" in nodeid):
        return
    from lib import git as git_mod

    monkeypatch.setattr(
        git_mod,
        "require_commit_identity",
        lambda *, cwd=None: ("Test", "test@example.com"),
    )


@pytest.fixture(autouse=True)
def _isolate_git_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    request: pytest.FixtureRequest,
) -> None:
    """Keep subprocess git off the live checkout (e2e suite uses tests/e2e/conftest.py)."""
    if request.node.get_closest_marker("e2e") is not None:
        return
    monkeypatch.chdir(tmp_path)
    strip_git_hook_env(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))


@pytest.fixture(autouse=True)
def _isolate_state_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect sqlite stores to throwaway paths for every test."""
    monkeypatch.setenv("MENTAT_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("MENTAT_DB", str(tmp_path / "mentat.db"))
    monkeypatch.setenv("MENTAT_LOG_PATH", str(tmp_path / "logs"))
    strip_git_hook_env(monkeypatch)
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
        "MENTAT_REPO",
    ):
        monkeypatch.delenv(key, raising=False)


def seed_agent_events(
    tmp_path: Path,
    repo: str,
    agent_id: str,
    events: list[dict],
    *,
    harness: str = "mentat-orchestrate",
    status: str = "running",
) -> Path:
    """Seed the canonical store and agent log dir for tests."""
    import os

    from lib import store

    log_path = tmp_path / "logs"
    session_dir = log_path / repo / agent_id
    session_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect()
    agents = store.AgentDAO(conn)
    if agents.get_by_id(agent_id) is None:
        started = str(events[0].get("ts", store.iso_now())) if events else store.iso_now()
        agents.insert(
            store.Agent(
                id=agent_id,
                supervisor_id=None,
                resumed_from_id=None,
                forked_from_id=None,
                harness=harness,
                pid=os.getpid() if status == "running" else None,
                status=status,  # type: ignore[arg-type]
                status_reason=None,
                started_at=started,
                ended_at=None,
            )
        )
    edao = store.EventDAO(conn)
    for ev in events:
        payload = ev.get("payload")
        if payload is None:
            payload = {k: v for k, v in ev.items() if k not in ("ts", "agent", "session", "event")}
        edao.append(
            kind=str(ev["event"]),
            payload=dict(payload),
            agent_id=agent_id,
            ts=ev.get("ts"),
        )
    conn.close()
    return session_dir


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
    init_git_repo(repo, ceiling=tmp_path)
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


def agent_events(agent_id: str) -> list[dict]:
    """Read canonical audit rows for one agent from the sqlite store."""
    from lib import store

    return store.list_events(agent_id)


def event_kinds(agent_id: str) -> list[str]:
    return [str(e.get("event", "")) for e in agent_events(agent_id)]


def events_by_kind(agent_id: str, kind: str) -> list[dict]:
    return [e for e in agent_events(agent_id) if e.get("event") == kind]
