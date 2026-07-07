"""Worktree preflight, main-tree guards, and teardown for mentat-implement."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_AGENTS_ROOT = Path(__file__).resolve().parents[4]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.chunk import bind_plan_chunk, get_chunk_id_from_env, make_chunk_id, set_chunk_id_in_env  # noqa: E402
from lib.exits import EX_SOFTWARE  # noqa: E402
from lib.support import paths  # noqa: E402

GIT_SCRIPT = paths.SKILLS_DIR / "mentat-git/scripts/git.py"
GIT_WORKTREE_PY = paths.SKILLS_DIR / "mentat-git/scripts/worktree.py"

_HARNESS_AGENT_DIRS: dict[str, str] = {
    "claude-code": ".claude",
    "cursor": ".cursor",
}


def skip_preflight(*, reuse_worktree: bool = False) -> bool:
    return reuse_worktree or bool(os.environ.get("MENTAT_SKIP_PREFLIGHT"))


def is_main_worktree(cwd: Path, *, git_worktree_py: Path | None = None) -> bool:
    """True iff cwd is inside the main worktree."""
    wt_py = git_worktree_py or GIT_WORKTREE_PY
    spec = importlib.util.spec_from_file_location("mentat_git_worktree", wt_py)
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"mentat-implement: worktree.py load failed: {e}", file=sys.stderr)
        return False
    return bool(mod.is_main_worktree(cwd))


def in_shared_main_tree(*, reuse_worktree: bool = False, git_worktree_py: Path | None = None) -> bool:
    if skip_preflight(reuse_worktree=reuse_worktree):
        return False
    cwd = Path.cwd()
    in_repo = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if in_repo.returncode != 0:
        return False
    return is_main_worktree(cwd, git_worktree_py=git_worktree_py)


def prune_worktrees_preflight() -> None:
    from lib import devcontainer, worktrees

    chunk_id = get_chunk_id_from_env()
    if not chunk_id:
        return
    wt_root = Path.cwd() / ".mentat" / "worktrees"
    worktrees.prune_stale(
        wt_root,
        active_slugs=set(devcontainer.list_active_slugs()),
        scope_chunk_ids={chunk_id},
    )


def repo_root_from_worktree(worktree: Path) -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        cwd=str(worktree),
    )
    if r.returncode == 0:
        common = Path(r.stdout.strip())
        return common.parent if common.name == ".git" else common
    return worktree.parents[2]


def teardown_worktree(target: Path) -> None:
    from lib import devcontainer, worktrees
    from lib.chunk import chunk_slug_from_worktree

    root = repo_root_from_worktree(target)
    try:
        cs = chunk_slug_from_worktree(target, root)
    except ValueError:
        cs = target.name
    devcontainer.down(cs)
    if worktrees.teardown(target):
        print(f"mentat-implement: removed clean worktree {target}", file=sys.stderr)
    else:
        print(f"mentat-implement: preserving dirty worktree {target}", file=sys.stderr)


def preflight_worktree(
    slug: str,
    *,
    reuse_worktree: bool = False,
    git_script: Path | None = None,
    git_worktree_py: Path | None = None,
    subprocess_mod: Any | None = None,
    in_shared_main_tree_fn: Any | None = None,
) -> tuple[int, Path | None]:
    if skip_preflight(reuse_worktree=reuse_worktree):
        return (0, None)
    script = git_script or GIT_SCRIPT
    if not script.exists():
        return (0, None)
    shared_main = (
        in_shared_main_tree_fn(reuse_worktree=reuse_worktree)
        if in_shared_main_tree_fn is not None
        else in_shared_main_tree(reuse_worktree=reuse_worktree, git_worktree_py=git_worktree_py)
    )
    if not shared_main:
        return (0, None)

    chunk_id = get_chunk_id_from_env() or make_chunk_id()
    set_chunk_id_in_env(chunk_id)
    bind_plan_chunk(slug, chunk_id)

    sp = subprocess if subprocess_mod is None else subprocess_mod
    result = sp.run(
        ["python3", str(script), "worktree", "create", slug, "--chunk-id", chunk_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return (result.returncode, None)
    line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    if not line:
        return (EX_SOFTWARE, None)
    target = Path(line)
    if not target.is_dir():
        return (EX_SOFTWARE, None)
    agent_id = os.environ.get("MENTAT_AGENT", f"implement-{slug}")
    from lib.chunk_service import ChunkService
    from lib import plans as _plans

    plan_path = _plans.resolve_plan_ref(slug)
    ChunkService.open().create(
        chunk_id=chunk_id,
        plan_slug=slug,
        plan_path=plan_path,
        agent_id=agent_id,
        worktree=target,
    )
    return (0, target)


def veto_agents_dir(harness: str) -> Path:
    dir_name = _HARNESS_AGENT_DIRS.get(harness, ".claude")
    return Path.home() / dir_name / "agents"


def preflight_veto_reviewers(
    harness: str,
    *,
    reuse_worktree: bool = False,
    veto_agents_dir_fn: Any | None = None,
) -> tuple[int, list[str]]:
    if skip_preflight(reuse_worktree=reuse_worktree):
        return (0, [])
    from lib.gates.score import missing_veto_reviewers as _missing

    agents_dir = veto_agents_dir_fn(harness) if veto_agents_dir_fn is not None else veto_agents_dir(harness)
    missing = _missing(agents_dir)
    return (1, missing) if missing else (0, [])
