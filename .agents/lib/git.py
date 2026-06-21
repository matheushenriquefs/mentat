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

    Fails safe: any git error (including missing .git) is treated as dirty to
    preserve un-landed work.  A missing .git gitlink (partial worktree remove)
    makes ``git status`` fail with rc != 0, which is caught by the error branch.
    """
    r = _run(["-C", str(path), "status", "--porcelain"])
    if r.returncode != 0:
        return True
    return bool(r.stdout.strip())


def remove_worktree(path: Path) -> bool:
    """``git worktree remove --force``. Returns True if path is gone afterward."""
    r = _run(["worktree", "remove", "--force", str(path)])
    return r.returncode == 0 or not path.exists()


def discard_path(cwd: Path, path: str) -> None:
    """Discard tracked changes and remove untracked files under *path* in the worktree.

    Best-effort — errors are silently ignored.  Used before rebase to remove
    transient files (e.g. .devcontainer/ modified by mentat-container up) that
    would cause git to refuse the rebase with "You have unstaged changes."
    """
    _run(["checkout", "--", path], cwd=cwd)
    _run(["clean", "-fd", path], cwd=cwd)


def rebase_ff_only(cwd: Path, onto: str) -> tuple[str | None, str | None]:
    """Rebase ``cwd`` branch onto ``onto``. Returns (tip_sha, None) or (None, err_msg).

    On failure, runs ``git rebase --abort`` (best-effort) so the worktree is not
    left mid-rebase and subsequent git ops can proceed cleanly.
    """
    r = _run(["rebase", onto], cwd=cwd)
    if r.returncode != 0:
        _run(["rebase", "--abort"], cwd=cwd)
        return None, r.stderr.strip()
    sha_r = _run(["rev-parse", "HEAD"], cwd=cwd)
    return sha_r.stdout.strip(), None


def ff_merge(cwd: Path, holding: str) -> str | None:
    """FF-merge cwd HEAD onto the explicit ``holding`` branch.

    Returns None on success.  Returns ``"not-ff"`` when the merge is genuinely
    not fast-forward (holding tip is not an ancestor of cwd HEAD).  Returns
    ``"git-error"`` for any git or setup failure (rev-parse, empty worktree
    list, update-ref / fetch error) so callers can report the correct cause.
    """
    sha_r = _run(["rev-parse", "HEAD"], cwd=cwd)
    if sha_r.returncode != 0:
        return "git-error"
    sha = sha_r.stdout.strip()
    entries = worktree_list(cwd=cwd)
    if not entries:
        return "git-error"
    main_wt = Path(entries[0]["worktree"])
    branch_r = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=main_wt)
    if branch_r.returncode != 0:
        return "git-error"
    current = branch_r.stdout.strip()
    if current == holding:
        # Branch is currently checked out — git fetch refuses to update it.
        # Use git update-ref instead (no working-tree touch, works dirty).
        # Verify ff first: holding tip must be an ancestor of sha.
        tip_r = _run(["rev-parse", f"refs/heads/{holding}"], cwd=main_wt)
        if tip_r.returncode != 0:
            return "git-error"
        anc = _run(["merge-base", "--is-ancestor", tip_r.stdout.strip(), sha], cwd=main_wt)
        if anc.returncode != 0:
            return "not-ff"
        r = _run(["update-ref", f"refs/heads/{holding}", sha], cwd=main_wt)
    else:
        # Branch is NOT checked out — git fetch . enforces ff automatically.
        r = _run(["fetch", ".", f"{sha}:refs/heads/{holding}"], cwd=main_wt)
    return None if r.returncode == 0 else "git-error"
