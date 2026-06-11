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
    r = _git(["worktree", "list", "--porcelain"], cwd=main_root)
    if r.returncode != 0:
        return False
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            registered = Path(line[len("worktree ") :]).resolve()
            if registered == target.resolve():
                return True
    return False


def _branch_exists(main_root: Path, branch: str) -> bool:
    r = _git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=main_root)
    return r.returncode == 0


def cmd_worktree_create(slug: str, *, base: str = "main", parent: Path | None = None) -> int:
    """Create sibling worktree at <parent>/<slug> on new branch <slug> from <base>.

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
        return 70

    if parent is None:
        parent = main_root.parent
    target = (parent / slug).resolve()

    if _existing_worktree(main_root, target):
        print(str(target))
        return 0

    if target.exists():
        print(
            f"mentat-git: path {target} exists but is not a registered worktree",
            file=sys.stderr,
        )
        return 65

    if not _branch_exists(main_root, base):
        print(f"mentat-git: base branch {base!r} does not exist", file=sys.stderr)
        return 66

    parent.mkdir(parents=True, exist_ok=True)

    r = _git(
        ["worktree", "add", "-b", slug, str(target), base],
        cwd=main_root,
    )
    if r.returncode != 0:
        # TOCTOU window: another process may have raced us between the
        # pre-checks above and `git worktree add`. Map git's stderr so the
        # caller still sees 65 (path conflict) / 66 (missing base) instead of
        # an opaque "unexpected git error".
        stderr_lower = (r.stderr or "").lower()
        if "already exists" in stderr_lower or "not an empty directory" in stderr_lower:
            print(f"mentat-git: path {target} exists but is not a registered worktree", file=sys.stderr)
            return 65
        if (
            "invalid reference" in stderr_lower
            or "unknown revision" in stderr_lower
            or "not a valid object name" in stderr_lower
        ):
            print(f"mentat-git: base branch {base!r} does not exist", file=sys.stderr)
            return 66
        print(f"mentat-git: worktree add failed:\n{r.stderr}", file=sys.stderr)
        return r.returncode or 70

    print(str(target))
    return 0
