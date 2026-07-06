"""mentat-git worktree subcommand.

Creates a sibling worktree at `<parent>/<slug>` on a new branch named `<slug>`,
forked from `<base>` (default `main`). Idempotent — re-running on an existing
mentat-managed worktree is a no-op.

Runs on host (git worktree add must touch main repo's .git/worktrees/).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib import git as _git_lib  # noqa: E402
from lib.chunk import chunk_slug, holding_branch, make_chunk_id  # noqa: E402
from lib.exits import EX_DATAERR, EX_NOINPUT, EX_SOFTWARE  # noqa: E402
from lib.worktrees import is_dirty, worktrees_root  # noqa: E402


def container_id_for_cwd() -> str | None:
    """Return container ID for the current worktree, or None."""
    from lib import devcontainer

    wt = Path.cwd()
    parts = wt.resolve().parts
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            return devcontainer.container_id_for_slug(f"{parts[i + 1]}/{parts[i + 2]}")
    return devcontainer.container_id_for_slug(wt.name)


def _git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def _main_repo_root(cwd: Path) -> Path | None:
    """Return the main worktree root for the repo containing cwd, or None."""
    r = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd)
    if r.returncode != 0:
        return None
    common_dir = Path(r.stdout.strip())
    return common_dir.parent if common_dir.name == ".git" else common_dir


def is_main_worktree(cwd: Path) -> bool:
    """True iff cwd is inside the main worktree (--git-dir == --git-common-dir)."""
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd)
    gd = _git(["rev-parse", "--path-format=absolute", "--git-dir"], cwd=cwd)
    if common.returncode != 0 or gd.returncode != 0:
        return False
    return Path(common.stdout.strip()).resolve() == Path(gd.stdout.strip()).resolve()


def _existing_worktree(main_root: Path, target: Path) -> bool:
    """True iff `target` is a path registered in `git worktree list`."""
    resolved = target.resolve()
    return any(Path(e["worktree"]).resolve() == resolved for e in _list_worktrees(main_root))


def _is_prunable_target(main_root: Path, target: Path) -> bool:
    """True iff `target` is registered as a prunable worktree (dir is gone)."""
    resolved = target.resolve()
    for e in _list_worktrees(main_root):
        if Path(e["worktree"]).resolve() == resolved:
            return "prunable" in e
    return False


def _branch_exists(main_root: Path, branch: str) -> bool:
    r = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=main_root)
    return r.returncode == 0


def _detect_default_branch(repo_root: Path) -> str:
    """Detect the repo's default branch. Detection order:
    1. git symbolic-ref --short refs/remotes/origin/HEAD (strip origin/ prefix)
    2. git symbolic-ref --short HEAD
    3. git config --get init.defaultBranch
    Raises GitError when none resolve.
    """
    r = _git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo_root)
    if r.returncode == 0:
        ref = r.stdout.strip()
        if ref.startswith("origin/"):
            return ref[len("origin/") :]
        if ref:
            return ref

    r = _git(["symbolic-ref", "--short", "HEAD"], cwd=repo_root)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()

    r = _git(["config", "--get", "init.defaultBranch"], cwd=repo_root)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()

    raise _git_lib.GitError("cannot detect default branch: no origin/HEAD, HEAD, or init.defaultBranch")


def _list_worktrees(main_root: Path) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into one dict per worktree.

    Each dict carries ``worktree`` (the path) and, when git flags it, ``prunable``
    (its working dir is gone but the admin record lingers).
    """
    return _git_lib.worktree_list(cwd=main_root)


def sweep_targets(main_root: Path) -> list[Path]:
    """Worktrees eligible for sweep: registered ones living outside
    ``<repo>/.mentat/worktrees/`` (parent-folder strays) plus any ``prunable``
    entries (e.g. a nested worktree whose dir was deleted). The main worktree and
    live managed worktrees are never returned.
    """
    managed = worktrees_root(main_root).resolve()
    main = main_root.resolve()
    targets: list[Path] = []
    for e in _list_worktrees(main_root):
        path = Path(e["worktree"]).resolve()
        if path == main:
            continue
        if managed not in path.parents or "prunable" in e:
            targets.append(path)
    return targets


def cmd_worktree_sweep(*, dry_run: bool = True) -> int:
    """List (default) or remove stray/prunable worktrees. Never auto-runs.

    Dry-run prints the targets and exits. A confirmed run (``dry_run=False``)
    does ``git worktree remove --force`` on each, then ``git worktree prune`` to
    clear the admin records of any whose dir was already gone, leaving
    ``git worktree list`` clean.

    A target holding uncommitted work is **preserved**, never force-removed —
    the same dirty-vs-clean safe default ``lib.worktrees`` enforces for managed
    teardown. ``--force`` is the operator's confirmation to remove, not a
    licence to discard un-landed work.

    Exit codes: 0 success / nothing to do; 70 not inside a git repo.
    """
    cwd = Path.cwd()
    main_root = _main_repo_root(cwd)
    if main_root is None:
        print("mentat-git: not inside a git repo", file=sys.stderr)
        return EX_SOFTWARE

    targets = sweep_targets(main_root)
    if not targets:
        print("mentat-git: no stray or prunable worktrees")
        return 0

    if dry_run:
        print("Would sweep (run with --force to remove):")
        for path in targets:
            mark = "  (dirty — will be preserved)" if is_dirty(path) else ""
            print(f"  {path}{mark}")
        return 0

    preserved: list[Path] = []
    attempted: list[Path] = []
    for path in targets:
        (preserved if is_dirty(path) else attempted).append(path)

    for path in attempted:
        _git(["worktree", "remove", "--force", str(path)], cwd=main_root)
    _git(["worktree", "prune"], cwd=main_root)

    # Count what is actually gone after remove + prune — a silently failed
    # remove must not be reported as swept.
    removed = sum(1 for path in attempted if not path.exists())
    print(f"mentat-git: swept {removed} worktree(s)")
    for path in preserved:
        print(f"mentat-git: preserved {path} (uncommitted changes)", file=sys.stderr)
    return 0


def cmd_worktree_create(
    slug: str,
    *,
    chunk_id: str | None = None,
    base: str | None = None,
    parent: Path | None = None,
) -> int:
    """Create sibling worktree at ``<parent>/<chunk_id>/<slug>`` on ``mentat/<chunk_id>/<slug>``.

    Exit codes:
      0  success or idempotent no-op
      65 path exists but is not a registered worktree
      66 base branch does not exist
      70 unexpected git error
    """
    cwd = Path.cwd()
    main_root = _main_repo_root(cwd)
    if main_root is None:
        print("mentat-git: not inside a git repo", file=sys.stderr)
        return EX_SOFTWARE

    _git_lib.sweep_bare_holding_refs(cwd=main_root)

    if chunk_id is None:
        chunk_id = make_chunk_id()

    if parent is None:
        parent = main_root / ".mentat" / "worktrees"
    cs = chunk_slug(chunk_id, slug)
    branch = holding_branch(cs)
    target = (parent / chunk_id / slug).resolve()

    # If the target has a stale admin record (prunable — dir is gone but record lingers),
    # prune it before the idempotency check so we don't return rc=0 with a missing dir.
    if _is_prunable_target(main_root, target):
        _git(["worktree", "prune"], cwd=main_root)

    if _existing_worktree(main_root, target):
        print(str(target))
        return 0

    if base is None:
        base = _detect_default_branch(main_root)

    if target.exists():
        print(
            f"mentat-git: path {target} exists but is not a registered worktree",
            file=sys.stderr,
        )
        return EX_DATAERR

    if not _branch_exists(main_root, base):
        print(f"mentat-git: base branch {base!r} does not exist", file=sys.stderr)
        return EX_NOINPUT

    parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    if _branch_exists(main_root, branch):
        r = _git(["worktree", "add", str(target), branch], cwd=main_root)
    else:
        r = _git(
            ["worktree", "add", "-b", branch, str(target), base],
            cwd=main_root,
        )
    if r.returncode != 0:
        # TOCTOU window: another process may have raced us between the
        # pre-checks above and `git worktree add`. Map git's stderr so the
        # caller still sees 65 (path conflict) / 66 (missing base) instead of
        # an opaque "unexpected git error".
        stderr_lower = (r.stderr or "").lower()
        if "a branch named" in stderr_lower and "already exists" in stderr_lower:
            r = _git(["worktree", "add", str(target), branch], cwd=main_root)
            if r.returncode == 0:
                print(str(target))
                return 0
        if "already exists" in stderr_lower or "not an empty directory" in stderr_lower:
            print(f"mentat-git: path {target} exists but is not a registered worktree", file=sys.stderr)
            return EX_DATAERR
        if (
            "invalid reference" in stderr_lower
            or "unknown revision" in stderr_lower
            or "not a valid object name" in stderr_lower
        ):
            print(f"mentat-git: base branch {base!r} does not exist", file=sys.stderr)
            return EX_NOINPUT
        print(f"mentat-git: worktree add failed:\n{r.stderr}", file=sys.stderr)
        return r.returncode or EX_SOFTWARE

    print(str(target))
    return 0
