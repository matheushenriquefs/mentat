"""Git subprocess seam. Single home for all porcelain parsing (ADR-0002). Stdlib only (ADR-0008)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from lib.chunk import chunk_slug, holding_branch
from lib.chunk import worktree_path as chunk_worktree_path


class GitError(RuntimeError):
    """A git target could not be resolved or a git operation failed."""


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


def worktree_for_chunk(chunk_id: str, slug: str, cwd: Path | None = None) -> Path:
    """Return the registered worktree for ``chunk_slug(chunk_id, slug)``.

    Raises ``GitError`` on miss — never falls back to ``Path.cwd()``.
    """
    root = repo_root(cwd)
    if root is None:
        raise GitError("not inside a git repository")
    cs = chunk_slug(chunk_id, slug)
    branch = holding_branch(cs)
    for entry in worktree_list(cwd=root):
        if entry.get("branch") == branch:
            return Path(entry["worktree"])
    expected = chunk_worktree_path(root, cs)
    if expected.is_dir():
        return expected
    raise GitError(f"no worktree for chunk {cs!r}")


def worktree_for_plan(plan_slug: str, cwd: Path | None = None) -> Path:
    """Resolve a plan slug via the bound chunk id registry."""
    from lib.chunk import bind_plan_chunk, chunk_id_for_plan

    try:
        chunk_id = chunk_id_for_plan(plan_slug)
    except LookupError:
        root = repo_root(cwd)
        if root is not None:
            wt_root = root / ".mentat" / "worktrees"
            matches = [p for p in wt_root.glob(f"*/{plan_slug}") if p.is_dir()]
            if len(matches) == 1:
                chunk_id = matches[0].parent.name
                bind_plan_chunk(plan_slug, chunk_id)
            else:
                raise GitError(f"no chunk_id bound for plan {plan_slug!r}") from None
        else:
            raise GitError(f"no chunk_id bound for plan {plan_slug!r}") from None
    return worktree_for_chunk(chunk_id, plan_slug, cwd=cwd)


def sweep_bare_holding_refs(cwd: Path | None = None) -> int:
    """Delete legacy ``refs/heads/mentat/<slug>`` branches (no chunk_id segment)."""
    root = repo_root(cwd)
    if root is None:
        return 0
    r = _run(["for-each-ref", "--format=%(refname:short)", "refs/heads/mentat/"], cwd=root)
    if r.returncode != 0:
        return 0
    removed = 0
    for line in r.stdout.splitlines():
        name = line.strip()
        if not name or name.count("/") != 1:
            continue
        if _run(["branch", "-D", name], cwd=root).returncode == 0:
            removed += 1
    return removed


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
    """Restore tracked files under *path* to HEAD in the worktree.

    Best-effort — errors are silently ignored.  Used before rebase to undo
    modifications to tracked files (e.g. .devcontainer/ patched by
    mentat-container up) that would cause git to refuse the rebase.

    Intentionally does NOT run ``git clean`` — synthesized overlay files
    (e.g. a generated devcontainer.json) are untracked and must survive rebase.
    Untracked files never block git rebase anyway.
    """
    _run(["checkout", "--", path], cwd=cwd)


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
    # Find which worktree (if any) has holding checked out — git fetch refuses
    # to update a currently-checked-out branch regardless of which worktree
    # holds it, so we must use update-ref via that worktree specifically.
    # entries[0] is always main per git docs, but holding may be checked out in
    # a linked worktree instead.
    holding_wt = next(
        (Path(e["worktree"]) for e in entries if e.get("branch") == holding),
        None,
    )
    if holding_wt is not None:
        # holding is currently checked out — verify ff then update-ref (no
        # working-tree touch, works dirty).
        tip_r = _run(["rev-parse", f"refs/heads/{holding}"], cwd=holding_wt)
        if tip_r.returncode != 0:
            return "git-error"
        anc = _run(["merge-base", "--is-ancestor", tip_r.stdout.strip(), sha], cwd=holding_wt)
        if anc.returncode != 0:
            return "not-ff"
        r = _run(["update-ref", f"refs/heads/{holding}", sha], cwd=holding_wt)
    else:
        # Not checked out anywhere — verify ff before fetch (fetch exit code alone
        # doesn't distinguish non-ff rejection from a true git error).
        main_wt = Path(entries[0]["worktree"])
        tip_r = _run(["rev-parse", f"refs/heads/{holding}"], cwd=main_wt)
        if tip_r.returncode != 0:
            return "git-error"
        anc = _run(["merge-base", "--is-ancestor", tip_r.stdout.strip(), sha], cwd=main_wt)
        if anc.returncode != 0:
            return "not-ff"
        r = _run(["fetch", ".", f"{sha}:refs/heads/{holding}"], cwd=main_wt)
    return None if r.returncode == 0 else "git-error"
