"""Shared worktree lifecycle: identity-by-path prune + single-worktree teardown.

A mentat worktree is one living under ``<repo>/.mentat/worktrees/`` — identity is
PATH, never a session-id name prefix. Any ``startswith`` heuristic on the name
would silently match nothing and orphan worktrees. Preserve-vs-remove is
dirty-vs-clean (``git status``), not a name guess.

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
# Preserved (dirty / ejected) worktrees are reclaimed only once this much older —
# far past the clean-prune cutoff — so a still-relevant leftover survives while an
# abandoned one cannot leak disk or leave its secrets in a stale tree forever.
DEFAULT_GC_SECONDS = 7 * 24 * 3600


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


def _iter_managed(wt_root: Path) -> list[Path]:
    """All managed worktree paths: flat ``worktrees/<slug>`` or ``worktrees/<cid>/<slug>``."""
    if not wt_root.is_dir():
        return []
    out: list[Path] = []
    for child in wt_root.iterdir():
        if not child.is_dir():
            continue
        if (child / ".git").exists():
            out.append(child)
            continue
        for sub in child.iterdir():
            if sub.is_dir() and (sub / ".git").exists():
                out.append(sub)
    return out


def chunk_slug_for_path(wt: Path, wt_root: Path) -> str:
    try:
        rel = wt.resolve().relative_to(wt_root.resolve())
        if len(rel.parts) == 2:
            return f"{rel.parts[0]}/{rel.parts[1]}"
        if len(rel.parts) == 1:
            return rel.parts[0]
    except ValueError:
        pass
    return wt.name


def _stale_managed(wt_root: Path, cutoff_seconds: int) -> list[Path]:
    cutoff = time.time() - cutoff_seconds
    return [c for c in _iter_managed(wt_root) if c.stat().st_mtime <= cutoff]


def prune_stale(
    wt_root: Path,
    *,
    active_slugs: set[str] | None = None,
    scope_chunk_ids: set[str] | None = None,
    cutoff_seconds: int = DEFAULT_CUTOFF_SECONDS,
) -> int:
    """Remove clean, inactive, stale worktrees under ``wt_root``. Returns count.

    When ``scope_chunk_ids`` is set, only worktrees whose chunk_id is in the set
    are candidates — another run's trees are never touched.
    """
    active = active_slugs or set()
    removed = 0
    for child in _stale_managed(wt_root, cutoff_seconds):
        cs = chunk_slug_for_path(child, wt_root)
        chunk_id = cs.split("/", 1)[0] if "/" in cs else cs
        if scope_chunk_ids is not None and chunk_id not in scope_chunk_ids:
            continue
        if cs in active or child.name in active:
            continue
        if is_dirty(child):
            continue
        if _remove(child):
            removed += 1
    return removed


def gc_preserved(
    wt_root: Path,
    *,
    active_slugs: set[str] | None = None,
    scope_chunk_ids: set[str] | None = None,
    gc_seconds: int = DEFAULT_GC_SECONDS,
) -> int:
    """Reclaim preserved worktrees older than ``gc_seconds``. Returns count."""
    active = active_slugs or set()
    removed = 0
    for child in _stale_managed(wt_root, gc_seconds):
        cs = chunk_slug_for_path(child, wt_root)
        chunk_id = cs.split("/", 1)[0] if "/" in cs else cs
        if scope_chunk_ids is not None and chunk_id not in scope_chunk_ids:
            continue
        if cs in active or child.name in active:
            continue
        if _remove(child):
            removed += 1
    return removed


def dirty_stale(wt_root: Path, *, cutoff_seconds: int = DEFAULT_CUTOFF_SECONDS) -> list[str]:
    """Names of stale worktrees that are dirty (hold un-landed work)."""
    return [chunk_slug_for_path(c, wt_root) for c in _stale_managed(wt_root, cutoff_seconds) if is_dirty(c)]
