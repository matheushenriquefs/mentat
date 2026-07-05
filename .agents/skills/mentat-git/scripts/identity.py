"""Git skill helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.config import read_config  # noqa: E402, F401


def container_id_for_cwd() -> str | None:
    """Return container ID for the current chunk-keyed worktree, or None."""
    from lib import devcontainer
    from lib.chunk import chunk_slug_from_worktree
    from lib.git import repo_root

    wt = Path.cwd()
    root = repo_root(wt)
    if root is None:
        return None
    try:
        cs = chunk_slug_from_worktree(wt, root)
    except ValueError:
        return None
    return devcontainer.container_id_for_slug(cs)
