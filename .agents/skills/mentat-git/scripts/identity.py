"""Git skill helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.config import read_config  # noqa: E402, F401


def container_id_for_cwd() -> str | None:
    """Return container ID for the current worktree, or None."""
    from lib import devcontainer

    wt = Path.cwd()
    parts = wt.resolve().parts
    for i, part in enumerate(parts):
        if part == "worktrees" and i + 2 < len(parts):
            return devcontainer.container_id_for_slug(f"{parts[i + 1]}/{parts[i + 2]}")
    return devcontainer.container_id_for_slug(wt.name)
