"""Shared worktree lifecycle: identity-by-path prune + single-worktree teardown.

A mentat worktree is one living under ``<repo>/.mentat/worktrees/`` — identity is
PATH, never a session-id name prefix. The S1 session-id rename obsoletes every
``startswith("mentat-"/"auto-"/"mentat-manual-")`` heuristic, which would
otherwise silently match nothing and orphan worktrees again. Preserve-vs-remove
is dirty-vs-clean (``git status``), not a name guess.

Lifecycle code lives here once; ``mentat-implement`` (own-worktree teardown on
its own failure + preflight sweep) and ``mentat-orchestrate`` (end-of-batch
sweep) both call it instead of re-implementing the loop.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

WORKTREES_SUBPATH = (".mentat", "worktrees")
DEFAULT_CUTOFF_SECONDS = 3600


def worktrees_root(repo_root: Path) -> Path:
    """``<repo_root>/.mentat/worktrees`` — where mentat worktrees live."""
    return repo_root.joinpath(*WORKTREES_SUBPATH)


def is_managed(path: Path, repo_root: Path) -> bool:
    """True iff ``path`` lives under ``<repo_root>/.mentat/worktrees/``."""
    root = worktrees_root(repo_root).resolve()
    try:
        return root in path.resolve().parents
    except OSError:
        return False


def is_dirty(path: Path) -> bool:
    """True iff the worktree has uncommitted changes (holds un-landed work)."""
    from lib import git as _git

    return _git.is_dirty(path)


def _remove(path: Path) -> bool:
    """Remove a worktree; fall back to rmtree if ``git worktree remove`` fails."""
    from lib import git as _git

    if not _git.remove_worktree(path):
        shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


def teardown(path: Path) -> bool:
    """Tear down a single worktree: remove if clean, preserve if dirty.

    Returns True iff removed. A dirty worktree holds un-landed work the operator
    must finish, so it is always preserved (False).
    """
    if is_dirty(path):
        return False
    return _remove(path)


def prune_stale(
    wt_root: Path,
    *,
    active_slugs: set[str] | None = None,
    cutoff_seconds: int = DEFAULT_CUTOFF_SECONDS,
) -> int:
    """Remove clean, inactive, stale worktrees under ``wt_root``. Returns count.

    Every child dir of ``wt_root`` is a managed worktree (identity-by-path).
    A worktree is removed iff it is older than the cutoff AND not active AND
    not dirty. Dirty worktrees are always preserved.
    """
    if not wt_root.is_dir():
        return 0
    active = active_slugs or set()
    cutoff = time.time() - cutoff_seconds
    removed = 0
    for child in wt_root.iterdir():
        if not child.is_dir():
            continue
        if child.stat().st_mtime > cutoff:
            continue
        if child.name in active:
            continue
        if is_dirty(child):
            continue
        if _remove(child):
            removed += 1
    return removed


def dirty_stale(wt_root: Path, *, cutoff_seconds: int = DEFAULT_CUTOFF_SECONDS) -> list[str]:
    """Names of stale worktrees that are dirty (hold un-landed work).

    Used to gate container pruning: if any stale worktree is dirty, container
    prune is skipped so the operator's leftovers keep a runnable container.
    """
    if not wt_root.is_dir():
        return []
    cutoff = time.time() - cutoff_seconds
    out: list[str] = []
    for child in wt_root.iterdir():
        if not child.is_dir() or child.stat().st_mtime > cutoff:
            continue
        if is_dirty(child):
            out.append(child.name)
    return out
