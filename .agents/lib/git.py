"""Git subprocess seam. Single home for all porcelain parsing (ADR-0002). Stdlib only (ADR-0008)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from lib.chunk import chunk_slug, holding_branch
from lib.chunk import worktree_path as chunk_worktree_path

_GIT_CEILING = "GIT_CEILING_DIRECTORIES"


class GitError(RuntimeError):
    """A git target could not be resolved or a git operation failed."""


def scrub_ambient_git_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Drop inherited GIT_/LEFTHOOK vars so hook context cannot steer git."""
    env = dict(base if base is not None else os.environ)
    for key in list(env):
        if key == _GIT_CEILING:
            continue
        if key.startswith("GIT_") or key.startswith("LEFTHOOK"):
            env.pop(key, None)
    return env


def _resolve_git_dirs(cwd: Path, env: dict[str, str]) -> tuple[str, str] | None:
    """Resolve absolute GIT_DIR and GIT_WORK_TREE for cwd under scrubbed env."""
    r = subprocess.run(
        ["git", "rev-parse", "--git-dir", "--show-toplevel"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        return None
    lines = [line.strip() for line in r.stdout.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    git_dir_raw, work_tree = lines[0], lines[1]
    git_dir_path = Path(git_dir_raw)
    if not git_dir_path.is_absolute():
        git_dir_raw = str((cwd / git_dir_raw).resolve())
    return git_dir_raw, work_tree


def git_subprocess_env(*, cwd: Path | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
    """Hermetic git env: scrub hook inheritance, pin GIT_DIR/GIT_WORK_TREE when cwd set."""
    env = scrub_ambient_git_env(base)
    if cwd is None or not cwd.is_dir():
        return env
    resolved = _resolve_git_dirs(cwd.resolve(), env)
    if resolved is None:
        return env
    git_dir, work_tree = resolved
    env["GIT_DIR"] = git_dir
    env["GIT_WORK_TREE"] = work_tree
    return env


def _effective_cwd(args: list[str], cwd: Path | None) -> Path | None:
    if cwd is not None:
        return cwd
    if len(args) >= 2 and args[0] == "-C":
        return Path(args[1])
    return None


def _run(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    effective = _effective_cwd(args, cwd)
    pin_cwd = effective if effective is not None and effective.is_dir() else None
    env = git_subprocess_env(cwd=pin_cwd)
    proc_cwd = str(cwd) if cwd is not None and cwd.is_dir() else None
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=proc_cwd,
        env=env,
    )


def repo_root(cwd: Path | None = None) -> Path | None:
    """Absolute repo root for cwd (None if not inside a git repo)."""
    r = _run(["rev-parse", "--show-toplevel"], cwd=cwd)
    if r.returncode != 0:
        return None
    return Path(r.stdout.strip())


def git_config_value(key: str, *, cwd: Path | None = None) -> str | None:
    """Return a git config value for key, or None when unset or empty."""
    r = _run(["config", key], cwd=cwd)
    val = r.stdout.strip()
    return val if r.returncode == 0 and val else None


def host_commit_identity(*, cwd: Path | None = None) -> dict[str, str]:
    """user.name/user.email from the repo's main worktree — empty dict when unset."""
    root = repo_root(cwd) or (cwd or Path.cwd())
    out: dict[str, str] = {}
    name = git_config_value("user.name", cwd=root)
    email = git_config_value("user.email", cwd=root)
    if name:
        out["user.name"] = name
    if email:
        out["user.email"] = email
    return out


def require_commit_identity(*, cwd: Path | None = None) -> tuple[str, str]:
    """Both user.name and user.email must be set — raises GitError otherwise."""
    ident = host_commit_identity(cwd=cwd)
    name = ident.get("user.name")
    email = ident.get("user.email")
    if not name or not email:
        raise GitError("git user.name and user.email must be set in the main worktree")
    return name, email


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
    if sha_r.returncode != 0:
        msg = sha_r.stderr.strip() or "rev-parse HEAD failed after rebase"
        return None, msg
    sha = sha_r.stdout.strip()
    if not sha:
        return None, "rev-parse HEAD returned empty tip after rebase"
    return sha, None


def ff_merge(cwd: Path, holding: str) -> str | None:
    """FF-merge cwd HEAD onto the explicit ``holding`` branch.

    Returns None on success.  Returns ``"not_ff"`` when the merge is genuinely
    not fast-forward (holding tip is not an ancestor of cwd HEAD).  Returns
    ``"git_error"`` for any git or setup failure (rev-parse, empty worktree
    list, update-ref / fetch error) so callers can report the correct cause.
    """
    sha_r = _run(["rev-parse", "HEAD"], cwd=cwd)
    if sha_r.returncode != 0:
        return "git_error"
    sha = sha_r.stdout.strip()
    entries = worktree_list(cwd=cwd)
    if not entries:
        return "git_error"
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
            return "git_error"
        anc = _run(["merge-base", "--is-ancestor", tip_r.stdout.strip(), sha], cwd=holding_wt)
        if anc.returncode != 0:
            return "not_ff"
        r = _run(["update-ref", f"refs/heads/{holding}", sha], cwd=holding_wt)
    else:
        # Not checked out anywhere — verify ff before fetch (fetch exit code alone
        # doesn't distinguish non-ff rejection from a true git error).
        main_wt = Path(entries[0]["worktree"])
        tip_r = _run(["rev-parse", f"refs/heads/{holding}"], cwd=main_wt)
        if tip_r.returncode != 0:
            return "git_error"
        anc = _run(["merge-base", "--is-ancestor", tip_r.stdout.strip(), sha], cwd=main_wt)
        if anc.returncode != 0:
            return "not_ff"
        r = _run(["fetch", ".", f"{sha}:refs/heads/{holding}"], cwd=main_wt)
    return None if r.returncode == 0 else "git_error"
