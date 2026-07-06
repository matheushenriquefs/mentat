"""E2E pytest isolation: ephemeral git sandboxes only.

Real-git journeys run under a agent-scoped temp tree. ``tmp_path`` is
redirected into that tree so subprocess git never discovers or mutates the live
checkout (including linked worktrees sharing the bind-mounted ``.git``).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT, init_git_repo, strip_git_hook_env

_LIVE_SNAPSHOT: dict[str, str] = {}
_SUBPROCESS_RUN = subprocess.run


def _live_git(*args: str) -> str:
    r = _SUBPROCESS_RUN(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout.strip()


@pytest.fixture(scope="function", autouse=True)
def _e2e_live_repo_guard() -> None:
    """Fail the e2e agent if any test mutates the real checkout."""
    try:
        _LIVE_SNAPSHOT["head"] = _live_git("rev-parse", "HEAD")
        _LIVE_SNAPSHOT["branch"] = _live_git("branch", "--show-current")
        _LIVE_SNAPSHOT["wt_list"] = _live_git("worktree", "list", "--porcelain")
    except subprocess.CalledProcessError, OSError:
        yield
        return
    yield
    assert _live_git("rev-parse", "HEAD") == _LIVE_SNAPSHOT["head"], "e2e mutated live HEAD"
    assert _live_git("branch", "--show-current") == _LIVE_SNAPSHOT["branch"], "e2e mutated live branch"
    assert _live_git("worktree", "list", "--porcelain") == _LIVE_SNAPSHOT["wt_list"], "e2e mutated live worktree list"


@pytest.fixture(scope="function")
def e2e_sandbox_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="mentat-e2e-"))
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def e2e_case_dir(e2e_sandbox_root: Path, request: pytest.FixtureRequest) -> Path:
    case = e2e_sandbox_root / f"{request.node.parent.name}__{request.node.name}"
    case.mkdir(parents=True, exist_ok=True)
    return case


@pytest.fixture
def tmp_path(e2e_case_dir: Path) -> Path:
    return e2e_case_dir


@pytest.fixture(autouse=True)
def _e2e_git_isolation(
    e2e_sandbox_root: Path,
    e2e_case_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(e2e_case_dir)
    strip_git_hook_env(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(e2e_sandbox_root))


@pytest.fixture(autouse=True)
def _e2e_agents_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Emit subprocesses resolve skills from the worktree under test."""
    monkeypatch.setenv("MENTAT_AGENTS_DIR", str(REPO_ROOT / ".agents"))


@pytest.fixture
def ephemeral_repo(e2e_sandbox_root: Path, e2e_case_dir: Path) -> Path:
    """Isolated git repo with a ``.mentat/`` stub under the e2e sandbox."""
    repo = e2e_case_dir / "repo"
    init_git_repo(repo, ceiling=e2e_sandbox_root)
    (repo / ".mentat").mkdir(exist_ok=True)
    return repo
