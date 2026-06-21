"""Git subprocess seam. Single home for all porcelain parsing (ADR-0002). Stdlib only (ADR-0008)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def repo_root(cwd: Path | None = None) -> Path | None:
    """Absolute repo root for cwd (None if not inside a git repo)."""
    r = _run(["rev-parse", "--show-toplevel"], cwd=cwd)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip())


def worktree_list(cwd: Path | None = None) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into one dict per worktree.

    Each dict carries ``worktree`` (path) and, when present, ``branch``
    (name after ``refs/heads/``), ``HEAD`` (sha), ``prunable`` (admin note).
    """
    r = _run(["worktree", "list", "--porcelain"], cwd=cwd)
    if r.returncode != 0:
        return []
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in r.stdout.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"worktree": line[len("worktree ") :]}
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/") :]
        elif line.startswith("HEAD "):
            cur["HEAD"] = line[len("HEAD ") :]
        elif line.startswith("prunable"):
            cur["prunable"] = line[len("prunable") :].strip()
    if cur:
        entries.append(cur)
    return entries


def worktree_for_slug(slug: str, cwd: Path | None = None) -> Path:
    """Path of the worktree whose branch matches ``slug``. Falls back to cwd."""
    for entry in worktree_list(cwd=cwd):
        if entry.get("branch") == slug:
            return Path(entry["worktree"])
    return Path.cwd()


def is_dirty(path: Path) -> bool:
    """True iff the worktree at path has uncommitted changes.

    Fails safe: a git error is treated as dirty to preserve un-landed work.
    """
    if not (path / ".git").exists():
        return False
    r = _run(["-C", str(path), "status", "--porcelain"])
    if r.returncode != 0:
        return True
    return bool(r.stdout.strip())


def remove_worktree(path: Path) -> bool:
    """``git worktree remove --force``. Returns True if path is gone afterward."""
    r = _run(["worktree", "remove", "--force", str(path)])
    return r.returncode == 0 or not path.exists()


def rebase_ff_only(cwd: Path, onto: str) -> tuple[str | None, str | None]:
    """Rebase ``cwd`` branch onto ``onto``. Returns (tip_sha, None) or (None, err_msg)."""
    r = _run(["rebase", onto], cwd=cwd)
    if r.returncode != 0:
        return None, r.stderr.strip()
    sha_r = _run(["rev-parse", "HEAD"], cwd=cwd)
    return sha_r.stdout.strip(), None


def ff_merge(cwd: Path) -> bool:
    """FF-merge cwd HEAD onto the main (first) worktree's current branch.

    Reads HEAD from cwd, locates the main worktree via worktree_list, and runs
    ``git merge --ff-only`` there. Returns False on any failure.
    """
    sha_r = _run(["rev-parse", "HEAD"], cwd=cwd)
    if sha_r.returncode != 0:
        return False
    sha = sha_r.stdout.strip()
    entries = worktree_list(cwd=cwd)
    if not entries:
        return False
    main_wt = Path(entries[0]["worktree"])
    r = _run(["merge", "--ff-only", sha], cwd=main_wt)
    return r.returncode == 0
