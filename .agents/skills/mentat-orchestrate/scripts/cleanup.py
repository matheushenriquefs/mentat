"""Container and worktree GC sweeps scoped to the current orchestrate run."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def prune_stale_containers(
    run_chunk_slugs: set[str],
    *,
    devcontainer_mod: Any,
    emit_event: Callable[[str, dict[str, object]], None],
) -> None:
    """Tear down exited containers for this run's chunk slugs only.

    Machine-wide docker prune is forbidden — it would reap a concurrent run's
    idle container (H3). Another run's resources are never candidates.
    """
    if not run_chunk_slugs:
        return
    removed = devcontainer_mod.down_run(run_chunk_slugs)
    emit_event("agent_reaped", {"reclaimed_bytes": None, "containers_removed": removed})


def prune_stale_worktrees(
    *,
    run_chunk_ids_fn: Callable[[], set[str]],
    preserve_chunk_slugs_fn: Callable[[set[str] | None], set[str]],
    preserve: set[str] | None = None,
    worktrees_mod: Any,
    emit_event: Callable[[str, dict[str, object]], None],
    wt_root: Path | None = None,
) -> None:
    """End-of-batch sweep of clean, inactive, stale worktrees for this run only.

    ``preserve`` plan slugs are held back from the sweep — a wedged (hitl_required)
    chunk's worktree must survive for the operator even when it is clean and
    inactive.
    """
    scope = run_chunk_ids_fn()
    if not scope:
        return
    root = wt_root if wt_root is not None else Path.cwd() / ".mentat" / "worktrees"
    active = preserve_chunk_slugs_fn(preserve)
    removed = worktrees_mod.prune_stale(root, active_slugs=active, scope_chunk_ids=scope)
    emit_event("agent_reaped", {"reclaimed_bytes": None, "worktrees_removed": removed})


def gc_preserved_worktrees(
    *,
    run_chunk_ids_fn: Callable[[], set[str]],
    preserve_chunk_slugs_fn: Callable[[set[str] | None], set[str]],
    preserve: set[str] | None = None,
    worktrees_mod: Any,
    emit_event: Callable[[str, dict[str, object]], None],
    wt_root: Path | None = None,
) -> None:
    """Reclaim long-abandoned preserved worktrees for this run's chunk ids only."""
    scope = run_chunk_ids_fn()
    if not scope:
        return
    root = wt_root if wt_root is not None else Path.cwd() / ".mentat" / "worktrees"
    active = preserve_chunk_slugs_fn(preserve)
    reclaimed = worktrees_mod.gc_preserved(root, active_slugs=active, scope_chunk_ids=scope)
    emit_event("agent_reaped", {"reclaimed_bytes": None, "worktrees_gc": reclaimed})
