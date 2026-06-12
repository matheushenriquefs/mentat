"""Git skill helpers."""

from __future__ import annotations

import sys
from pathlib import Path

_AGENTS_ROOT = Path(__file__).resolve().parents[3]
if str(_AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENTS_ROOT))

from lib.jsonc import read_config  # noqa: E402, F401


def container_id_for_cwd() -> str | None:
    """Return container ID for the current worktree slug, or None."""
    from lib import devcontainer

    slug = Path.cwd().name
    return devcontainer.container_id_for_slug(slug)
